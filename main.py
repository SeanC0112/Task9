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
'port': 2000,  # connection port
'town': 'Town03',  # which town to simulate
'max_time_episode': 1000,  # maximum timesteps per episode
'max_waypt': 12,  # maximum number of waypoints
'obs_range': 32,  # observation range (meter)
'lidar_bin': 0.125,  # bin size of lidar sensor (meter)
'd_behind': 12,  # distance behind the ego vehicle (meter)
'out_lane_thres': 2.0,  # threshold for out of lane
'desired_speed': 8,  # desired speed (m/s)
'max_ego_spawn_times': 200,  # maximum times to spawn ego vehicle
'display_route': False,  # whether to render the desired route
}

is_fork = multiprocessing.get_start_method() == "fork"
device = (
    torch.device(0)
    if torch.cuda.is_available() and not is_fork
    else torch.device("cpu")
)
torch.set_default_device(device)
num_cells = 256  # number of cells in each layer i.e. output dim.
lr = 8e-5
max_grad_norm = 1.0

frames_per_batch = 1000
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

base_env = GymEnv("carla-v0", params=params, render_mode="human", lap_complete_percent=0.95, domain_randomize=False, continuous=True, device=device)