import gymnasium as gym
import gym_carla
import carla
import os
import warnings
warnings.filterwarnings("ignore")
from torch import multiprocessing

from collections import defaultdict

import matplotlib.pyplot as plt
import torch
from tensordict.nn import TensorDictModule
from tensordict.nn.distributions import NormalParamExtractor
from torch import multiprocessing, nn

from torchrl.collectors import Collector
from torchrl.data.replay_buffers import ReplayBuffer
from torchrl.data.replay_buffers.samplers import SamplerWithoutReplacement
from torchrl.data.replay_buffers.storages import LazyTensorStorage
from torchrl.envs import (
    Compose,
    CatFrames,
    ToTensorImage,
    StepCounter,
    TransformedEnv,
    ObservationNorm,
    DoubleToFloat,
    DTypeCastTransform
)
from torchrl.envs.libs.gym import GymEnv
from torchrl.envs.utils import check_env_specs, ExplorationType, set_exploration_type
from torchrl.modules import ProbabilisticActor, TanhNormal, ValueOperator
from torchrl.objectives import ClipPPOLoss
from torchrl.objectives.value import GAE
from tqdm import tqdm


# parameters for the gym_carla environment
params = {
'number_of_vehicles': 1,
'number_of_walkers': 0,
'display_size': 256,  # screen size of bird-eye render
'max_past_step': 1,  # the number of past steps to draw
'dt': 0.1,  # time interval between two frames
'discrete': False,  # whether to use discrete control space
'discrete_acc': [-3.0, 0.0, 3.0],  # discrete value of accelerations
'discrete_steer': [-0.2, 0.0, 0.2],  # discrete value of steering angles
'continuous_accel_range': [-3.0, 3.0],  # continuous acceleration range
'continuous_steer_range': [-0.3, 0.3],  # continuous steering angle range
'ego_vehicle_filter': 'vehicle.lincoln*',  # filter for defining ego vehicle
'port': 2001,  # connection port
'town': 'Town03',  # which town to simulate
'task_mode': 'random',  # mode of the task, [random, roundabout (only for Town03)]
'max_time_episode': 1000,  # maximum timesteps per episode
'max_waypt': 12,  # maximum number of waypoints
'obs_range': 32,  # observation range (meter)
'lidar_bin': 0.125,  # bin size of lidar sensor (meter)
'd_behind': 12,  # distance behind the ego vehicle (meter)
'out_lane_thres': 2.0,  # threshold for out of lane
'desired_speed': 8,  # desired speed (m/s)
'max_ego_spawn_times': 200,  # maximum times to spawn ego vehicle
'display_route': True,  # whether to render the desired route
'pixor_size': 64,  # size of the pixor labels
'pixor': False,  # whether to output PIXOR observation
}

is_fork = multiprocessing.get_start_method() == "fork"
device = (
    torch.device(0)
    if torch.cuda.is_available() and not is_fork
    else torch.device("cpu")
)

print(f"Using device: {device}")

torch.set_default_device(device)
num_cells = 256  # number of cells in each layer i.e. output dim.
lr = 8e-5
max_grad_norm = 1.0

frames_per_batch = 300
# For a complete training, bring the number of frames up to 1M
total_frames = 750000

sub_batch_size = 64  # cardinality of the sub-samples gathered from the current data in the inner loop
num_epochs = 10  # optimization steps per batch of data collected
clip_epsilon = (
    0.2  # clip value for PPO loss: see the equation in the intro for more context.
)
gamma = 0.99
lmbda = 0.95
entropy_eps = 12e-3

class ActorNet(nn.Module):
    def __init__(self, actions):
        super().__init__()
        self.cnn = nn.Sequential(
            nn.LazyConv2d(32, kernel_size=10, stride=2),
            nn.ReLU(),
            nn.LazyConv2d(64, kernel_size=6, stride=2),
            nn.ReLU(),
            nn.LazyConv2d(64, kernel_size=4, stride=2),
            nn.ReLU(),
            nn.Flatten(start_dim=1, end_dim=-1),
            nn.LazyLinear(256),
        )
        self.mlp = nn.Sequential(
            nn.LazyLinear(528),
            nn.ReLU(),
            nn.LazyLinear(256),
            nn.ReLU(),
            nn.LazyLinear(128),
            nn.ReLU(),
            nn.LazyLinear(actions.shape[-1] * 2),
            NormalParamExtractor(),
        )


    def forward(self, lidar, state):
        print("lidar shape:", lidar.shape)
        print("state shape:", state.shape)
        no_batch = lidar.dim() == 3
        lidar = lidar.movedim(-1, -3)
        if no_batch:
            lidar = lidar.unsqueeze(0)      

        cnn_out = self.cnn(lidar)

        if no_batch:
            cnn_out = cnn_out.squeeze(0)

        print("cnn_out shape:", cnn_out.shape)
        print("state shape after unsqueeze:", state.shape)
        concatenated = torch.cat([cnn_out, state], dim=-1)
        mlp_out = self.mlp(concatenated)
        return mlp_out

class ValueNet(nn.Module):
    def __init__(self, actions):
        super().__init__()
        self.cnn = nn.Sequential(
            nn.LazyConv2d(32, kernel_size=10, stride=2),
            nn.ReLU(),
            nn.LazyConv2d(64, kernel_size=6, stride=2),
            nn.ReLU(),
            nn.LazyConv2d(64, kernel_size=4, stride=2),
            nn.ReLU(),
            nn.Flatten(start_dim=1, end_dim=-1),
            nn.LazyLinear(256),
        )
        self.mlp = nn.Sequential(
            nn.LazyLinear(528),
            nn.ReLU(),
            nn.LazyLinear(256),
            nn.ReLU(),
            nn.LazyLinear(128),
            nn.ReLU(),
            nn.LazyLinear(1),
        )

    def forward(self, lidar, state):
        print("lidar shape:", lidar.shape)
        print("state shape:", state.shape)
        no_batch = lidar.dim() == 3
        lidar = lidar.movedim(-1, -3)
        if no_batch:
            lidar = lidar.unsqueeze(0)

        cnn_out = self.cnn(lidar)

        if no_batch:
            cnn_out = cnn_out.squeeze(0)

        concatenated = torch.cat([cnn_out, state], dim=-1)
        mlp_out = self.mlp(concatenated)
        return mlp_out

base_env = GymEnv("carla-v0", params=params, device=device)

env = TransformedEnv(
    base_env,
    Compose(
        DTypeCastTransform(dtype_in=torch.uint8, dtype_out=torch.float32, in_keys=["lidar"]),
        # normalize observations
        # ObservationNorm(in_keys=["lidar"]),
        DoubleToFloat(),
        StepCounter(),
    ),
)

# env.transform[1].init_stats(num_iter=1000, reduce_dim=0, cat_dim=0)


check_env_specs(env)


print("Observation spec:", env.observation_spec)
print("Action spec:", env.action_spec)

actor_net = ActorNet(env.action_spec)
value_net = ValueNet(env.action_spec)
obs = env.reset()

actor_net.forward(obs["lidar"], obs["observation"])
value_net.forward(obs["lidar"], obs["observation"])

policy_module = TensorDictModule(
    actor_net,
    in_keys=["lidar", "observation"],
    out_keys=["loc", "scale"],
    )

policy_module = ProbabilisticActor(
    module=policy_module,
    spec=env.action_spec,
    in_keys=["loc", "scale"],
    distribution_class=TanhNormal,
    # distribution_kwargs={
    #     "low": env.action_spec_unbatched.space.low,
    #     "high": env.action_spec_unbatched.space.high,
    # },
    return_log_prob=True,
)


value_module = ValueOperator(
    module=value_net,
    in_keys=["lidar", "observation"],
)

collector = Collector(
    env,
    policy_module,
    frames_per_batch=frames_per_batch,
    total_frames=total_frames,
    split_trajs=False,
    device=device,
)

replay_buffer = ReplayBuffer(
    storage=LazyTensorStorage(max_size=frames_per_batch),
    sampler=SamplerWithoutReplacement(),
)

advantage_module = GAE(
    gamma=gamma, lmbda=lmbda, value_network=value_module, average_gae=True
)

loss_module = ClipPPOLoss(
    actor_network=policy_module,
    critic_network=value_module,
    clip_epsilon=clip_epsilon,
    entropy_bonus=bool(entropy_eps),
    entropy_coeff=entropy_eps,
    # these keys match by default but we set this for completeness
    critic_coeff=1.0,
    loss_critic_type="smooth_l1",
)

optim = torch.optim.Adam(loss_module.parameters(), lr)
scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
    optim, total_frames // frames_per_batch, 0.0
)

# scheduler = torch.optim.lr_scheduler.LinearLR(optim, 1.0, 0.0, total_frames // frames_per_batch)

logs = defaultdict(list)
pbar = tqdm(total=total_frames)
eval_str = ""

# We iterate over the collector until it reaches the total number of frames it was
# designed to collect:
for i, tensordict_data in enumerate(collector):
    # we now have a batch of data to work with. Let's learn something from it.
    for _ in range(num_epochs):
        # We'll need an "advantage" signal to make PPO work.
        # We re-compute it at each epoch as its value depends on the value
        # network which is updated in the inner loop.
        advantage_module(tensordict_data)
        data_view = tensordict_data.reshape(-1)
        replay_buffer.extend(data_view.cpu())
        for _ in range(frames_per_batch // sub_batch_size):
            subdata = replay_buffer.sample(sub_batch_size)
            loss_vals = loss_module(subdata.to(device))
            loss_value = (
                loss_vals["loss_objective"]
                + loss_vals["loss_critic"]
                + loss_vals["loss_entropy"]
            )

            # Optimization: backward, grad clipping and optimization step
            loss_value.backward()
            # this is not strictly mandatory but it's good practice to keep
            # your gradient norm bounded
            torch.nn.utils.clip_grad_norm_(loss_module.parameters(), max_grad_norm)
            optim.step()
            optim.zero_grad()

    logs["reward"].append(tensordict_data["next", "reward"].mean().item())
    pbar.update(tensordict_data.numel())
    cum_reward_str = (
        f"average reward={logs['reward'][-1]: 4.4f} (init={logs['reward'][0]: 4.4f})"
    )
    logs["step_count"].append(tensordict_data["step_count"].max().item())
    stepcount_str = f"step count (max): {logs['step_count'][-1]}"
    logs["lr"].append(optim.param_groups[0]["lr"])
    lr_str = f"lr policy: {logs['lr'][-1]: 4.4f}"
    if i % 10 == 0:
        # We evaluate the policy once every 10 batches of data.
        # Evaluation is rather simple: execute the policy without exploration
        # (take the expected value of the action distribution) for a given
        # number of steps (1000, which is our ``env`` horizon).
        # The ``rollout`` method of the ``env`` can take a policy as argument:
        # it will then execute this policy at each step.
        with set_exploration_type(ExplorationType.DETERMINISTIC), torch.no_grad():
            # execute a rollout with the trained policy
            eval_rollout = env.rollout(1000, policy_module)
            logs["eval reward"].append(eval_rollout["next", "reward"].mean().item())
            logs["eval reward (sum)"].append(
                eval_rollout["next", "reward"].sum().item()
            )
            logs["eval step_count"].append(eval_rollout["step_count"].max().item())
            eval_str = (
                f"eval cumulative reward: {logs['eval reward (sum)'][-1]: 4.4f} "
                f"(init: {logs['eval reward (sum)'][0]: 4.4f}), "
                f"eval step-count: {logs['eval step_count'][-1]}"
            )
            del eval_rollout
    pbar.set_description(", ".join([eval_str, cum_reward_str, stepcount_str, lr_str]))

    # We're also using a learning rate scheduler. Like the gradient clipping,
    # this is a nice-to-have but nothing necessary for PPO to work.
    scheduler.step()
    for filename in os.listdir('.plots'):
        os.remove(os.path.join('.plots', filename))
    plt.figure(figsize=(10, 10))
    plt.subplot(2, 2, 1)
    plt.plot(logs["reward"])
    plt.title("training rewards (average)")
    plt.subplot(2, 2, 2)
    plt.plot(logs["step_count"])
    plt.title("Max step count (training)")
    plt.subplot(2, 2, 3)
    plt.plot(logs["eval reward (sum)"])
    plt.title("Return (test)")
    plt.subplot(2, 2, 4)
    plt.plot(logs["eval step_count"])
    plt.title("Max step count (test)")
    plt.savefig('.plots/plot.png')
    plt.close() 