import matplotlib.pyplot as plt
import numpy as np
import sympy as sp
import sys, os, sympy, shutil, math
import site
site.addsitedir('../src')

# import xmltodict
# import pickle
import json
# import pandas
import pylab
from os import listdir
import pandas as pd
# import visuals
import dolfin

import os.path
import argparse

from postprocess import load_data

print('postproc fields')

import mpi4py

comm = mpi4py.MPI.COMM_WORLD
rank = comm.Get_rank()
size = comm.Get_size()

parser = argparse.ArgumentParser()
parser.add_argument("--experiment", "-e", type=str, default=None, help='folder containing xdmf data')
parser.add_argument("--stride", "-s", type=int, default=10, help='stride of temporal sampling')
parser.add_argument("--xres", "-nx", type=int, default=100, help='spatial resolution (points)')
args, unknown = parser.parse_known_args()
print(args)
if args.experiment is not None:
    rootdir = args.experiment
print(rootdir)
stride = args.stride


params, data, signature = load_data(rootdir)

mesh = dolfin.Mesh(comm, os.path.join(rootdir, 'mesh.xml'))
V_alpha = dolfin.FunctionSpace(mesh, "CG", 1)

load_min = params['time_stepping']['load_min']
load_max = params['time_stepping']['load_max']
nsteps = params['time_stepping']['nsteps']
Lx = params['geometry']['Lx']

onedim = True
if not onedim:
	Ly = params['geometry']['Ly']

xs = np.linspace(-Lx/2, Lx/2, args.xres)
y0 = 0.

load_steps = np.linspace(load_min, load_max, nsteps)

beta0 = dolfin.Function(V_alpha)
alpha = dolfin.Function(V_alpha)
alpha_old = dolfin.Function(V_alpha)
alpha_bif = dolfin.Function(V_alpha)

maxmodes = 2

alpha = dolfin.Function(V_alpha)
alphas = []

file_postproc = dolfin.XDMFFile(os.path.join(rootdir, "output_postproc.xdmf"))
file_postproc.parameters["functions_share_mesh"] = True
file_postproc.parameters["flush_output"] = True

# stride = 10
for (step, load) in enumerate(load_steps):
	if not step % stride:
		with file_postproc as file:
			print('DEBUG: reading file', os.path.join(rootdir, "output_postproc.xdmf"))
			print('DEBUG: reading step', step)
			file_postproc.read_checkpoint(alpha, 'alpha-{}'.format(step), 0)
			# import pdb; pdb.set_trace()
			if onedim:
				alphav = [alpha(x) for x in xs]
			else:
				alphav = [alpha(x, y0) for x in xs]
			alphas.append(alphav)

np.save(os.path.join(rootdir, "alpha"), alphas,
	allow_pickle=True, fix_imports=True)
print('Saved {}'.format(os.path.join(rootdir, 'alpha.npy')))
data = np.load(os.path.join(rootdir, "alpha.npy".format(0)))


perturbations = []


betan = dolfin.Function(V_alpha)
maxmodes = 1
fields = []
h0=0
fields = [beta0, alpha_old, alpha_bif, alpha]
try:
	with dolfin.XDMFFile(os.path.join(rootdir, "bifurcation_postproc.xdmf")) as file:
	# with dolfin.XDMFFile(os.path.join(rootdir, "postproc.xdmf")) as file:
		file.read_checkpoint(beta0, 'beta0')
		file.read_checkpoint(alpha, 'alpha')
		file.read_checkpoint(alpha_old, 'alpha-old')
		file.read_checkpoint(alpha_bif, 'alpha-bif')

	for field, name in zip(fields, ['beta0', 'alpha_old', 'alpha_bif', 'alpha0']):
		if onedim:
			fieldv = [field(x) for x in xs]
		else:
			fieldv = [field(x, h0) for x in xs]
		print('saving {}'.format(name))
		np.save(os.path.join(rootdir, name), fieldv,
			allow_pickle=True, fix_imports=True)

	for n in range(maxmodes):
		modename = 'beta-%d'%n
		print(modename)
		file.read_checkpoint(betan, modename)

		perturbations.append(betan)
		if onedim:
			betanv = [betan(x) for x in xs]
		else:
			betanv = [betan(x, h0) for x in xs]
		np.save(os.path.join(rootdir, "beta-{}".format(n)), betanv,
			allow_pickle=True, fix_imports=True)

except Exception as e: 
	print(e)
	# print('no bifurcation data found')
# else:
# 	pass
# finally:
# 	pass



# nmodes = len(perturbations)


# ------------


# z = np.polyfit(htest, en, m)
# p = np.poly1d(z)

# 3
# np.linspace(hmin, hmax, 4)





