import sys
sys.path.append("../src/")
import numpy as np
import sympy
import pandas as pd
import os
import dolfin
import ufl
import matplotlib.pyplot as plt
import solvers
from damage_elasticity_model import DamagePrestrainedElasticityModel
from utils import ColorPrint, get_versions
from post_processing import make_figures, plot_global_data
# set_log_level(100)
dolfin.parameters["std_out_all_processes"] = False


dolfin.parameters["linear_algebra_backend"] = "PETSc"
from functools import reduce
from petsc4py import PETSc
import hashlib
from dolfin import MPI
from dolfin import *
import petsc4py
import post_processing as pp
from slepc_eigensolver import EigenSolver
from pathlib import Path
import json
from string import Template
from subprocess import Popen, PIPE, check_output
import numpy as np

from solver_stability import StabilitySolver
# from solver_stability_periodic import StabilitySolver
from time_stepping import TimeStepping
from copy import deepcopy
from linsearch import LineSearch

import os.path
import os

import mpi4py

comm = mpi4py.MPI.COMM_WORLD
rank = comm.Get_rank()
size = comm.Get_size()



form_compiler_parameters = {
    "representation": "uflacs",
    "quadrature_degree": 2,
    "optimize": True,
    "cpp_optimize": True,
}

dolfin.parameters["form_compiler"].update(form_compiler_parameters)
# np.set_printoptions(threshold=np.nan)
timestepping_parameters = {"perturbation_choice": 'steepest',
                            "savelag": 1,
                            "outdir": '',
                            'cont_rtol': 1e-5}
                        # "perturbation_choice": 'steepest',               # admissible choices: steepest, first, #

stability_parameters = {"order": 4,
                        "checkstability": True,
                        "continuation": False,
                        "projection": 'none',
                        'maxmodes': 5,
                        }

petsc_options_alpha_tao = {"tao_type": "gpcg",
                           "tao_ls_type": "gpcg",
                           "tao_gpcg_maxpgits": 50,
                           "tao_max_it": 300,
                           "tao_steptol": 1e-7,
                           "tao_gatol": 1e-5,
                           "tao_grtol": 1e-5,
                           "tao_gttol": 1e-5,
                           "tao_catol": 0.,
                           "tao_crtol": 0.,
                           "tao_ls_ftol": 1e-6,
                           "tao_ls_gtol": 1e-6,
                           "tao_ls_rtol": 1e-6,
                           "ksp_rtol": 1e-6,
                           "tao_ls_stepmin": 1e-8,  #
                           "tao_ls_stepmax": 1e6,  #
                           "pc_type": "bjacobi",
                           "tao_monitor": "",  # "tao_ls_type": "more-thuente"
                           # "ksp_type": "preonly"  # "tao_ls_type": "more-thuente"
                           }
# vinewtonrsls
petsc_options_alpha_snes = {
    "alpha_snes_type": "vinewtonrsls",
    "alpha_snes_stol": 1e-5,
    "alpha_snes_atol": 1e-5,
    "alpha_snes_rtol": 1e-5,
    "alpha_snes_max_it": 500,
    "alpha_ksp_type": "preonly",
    "alpha_pc_type": "lu"}

petsc_options_u = {
    "u_snes_type": "newtontr",
    "u_snes_stol": 1e-6,
    "u_snes_atol": 1e-6,
    "u_snes_rtol": 1e-6,
    "u_snes_max_it": 1000,
    "u_snes_monitor": ''}

alt_min_parameters = {"max_it": 300,
                      "tol": 1.e-5,
                      "solver_alpha": "tao",
                      "solver_u": petsc_options_u,
                      # "solver_alpha_snes": petsc_options_alpha_snes
                     "solver_alpha_tao": petsc_options_alpha_tao
                     }

versions = get_versions()
versions.update({'filename': __file__})
parameters = {"alt_min": alt_min_parameters,
                # "solver_u": petsc_options_u,
                # "solver_alpha_tao": petsc_options_alpha_tao, "solver_alpha_snes": petsc_options_alpha_snes,
                "stability": stability_parameters,
                "time_stepping": timestepping_parameters,
                "material": {},
                "geometry": {},
                "experiment": {},
                "code": versions
                }


# constants
ell = 0.1
Lx = 1
Ly = 0.1
load_min = 0.9
load_max = 1.1
nsteps = 10
outdir = "output"
savelag = 1
nu = dolfin.Constant(0.)
ell = dolfin.Constant(ell)
E0 = dolfin.Constant(1.0)
sigma_D0 = E0
n = 5



def traction_test(
    ell=0.05,
    ell_e=.1,
    degree=1,
    n=3,
    nu=0.,
    load_min=0,
    load_max=2,
    loads=None,
    nsteps=20,
    Lx=1.,
    Ly=0.1,
    outdir="outdir",
    postfix='',
    savelag=1,
    sigma_D0=1.,
    periodic=False,
    continuation=False,
    checkstability=True,
    configString='',
    test=True
):
    # constants
    # ell = ell
    Lx = Lx
    load_min = load_min
    load_max = load_max
    nsteps = nsteps
    outdir = outdir
    loads=loads

    savelag = 1
    nu = dolfin.Constant(nu)
    ell = dolfin.Constant(ell)
    ell_e = ell_e
    E = dolfin.Constant(1.0)
    K = E.values()[0]/ell_e**2.
    sigma_D0 = E
    n = n
    # h = ell.values()[0]/n
    h = max(ell.values()[0]/n, .005)
    cell_size = h
    continuation = continuation
    isPeriodic = periodic
    config = json.loads(configString) if configString != '' else ''

    cmd_parameters =  {
    'material': {
        "ell": ell.values()[0],
        "ell_e": ell_e,
        "K": K,
        "E": E.values()[0],
        "nu": nu.values()[0],
        "sigma_D0": sigma_D0.values()[0]},
    'geometry': {
        'Lx': Lx,
        'Ly': Ly,
        'n': n,
        },
    'experiment': {
        'test': test,
        'periodic': isPeriodic,
        'signature': ''
        },
    'stability': {
        'checkstability' : checkstability,
        'continuation' : continuation
        },
    'time_stepping': {
        'load_min': load_min,
        'load_max': load_max,
        'nsteps':  nsteps,
        'outdir': outdir,
        'postfix': postfix,
        'savelag': savelag},
    'alt_min': {}, "code": {}

    }



    # --------------------

    for par in parameters: parameters[par].update(cmd_parameters[par])

    if config:
        # import pdb; pdb.set_trace()
        for par in config: parameters[par].update(config[par])
    # else:

    # parameters['material']['ell_e'] = 

    Lx = parameters['geometry']['Lx']
    Ly = parameters['geometry']['Ly']
    ell = parameters['material']['ell']
    ell_e = parameters['material']['ell_e']

    BASE_DIR = os.path.dirname(os.path.realpath(__file__))
    fname="film"
    print(BASE_DIR)
    os.path.isfile(fname)

    signature = hashlib.md5(str(parameters).encode('utf-8')).hexdigest()
    
    if parameters['experiment']['test'] == True: outdir += '-{}'.format(cmd_parameters['time_stepping']['postfix'])
    else: outdir += '-{}{}'.format(signature, cmd_parameters['time_stepping']['postfix'])
    
    parameters['time_stepping']['outdir']=outdir
    Path(outdir).mkdir(parents=True, exist_ok=True)
    print('Outdir is: '+outdir)

    with open(os.path.join(outdir, 'rerun.sh'), 'w') as f:
        configuration = deepcopy(parameters)
        configuration['time_stepping'].pop('outdir')
        str(configuration).replace("\'True\'", "True").replace("\'False\'", "False")
        rerun_cmd = 'python3 {} --config="{}"'.format(os.path.basename(__file__), configuration)
        f.write(rerun_cmd)

    with open(os.path.join(outdir, 'parameters.pkl'), 'w') as f:
        json.dump(parameters, f)

    with open(os.path.join(outdir, 'signature.md5'), 'w') as f:
        f.write(signature)
    print(parameters)
    
    # import pdb; pdb.set_trace()

    # boundary_meshfunction = dolfin.MeshFunction("size_t", mesh, "meshes/%s-%s_facet_region.xml"%(fname, signature))
    # cells_meshfunction = dolfin.MeshFunction("size_t", mesh, "meshes/%s-%s_physical_region.xml"%(fname, signature))

    # ------------------
    geometry_parameters = parameters['geometry']

    geom_signature = hashlib.md5(str(geometry_parameters).encode('utf-8')).hexdigest()
    meshfile = "%s/meshes/circle-%s.xml"%(BASE_DIR, geom_signature)
    # cmd_parameters['experiment']['signature']=signature
    meshsize = parameters['material']['ell']/parameters['geometry']['n']
    d={'rad': parameters['geometry']['Lx'], 'Ly': parameters['geometry']['Ly'],
        'meshsize': meshsize}

    if os.path.isfile(meshfile):
        print("Meshfile %s exists"%meshfile)
        mesh = dolfin.Mesh("meshes/circle-%s.xml"%(geom_signature))
    else:
        print("Creating meshfile: %s"%meshfile)
        print("DEBUG: parameters: %s"%parameters['geometry'])

        mesh_template = open('templates/circle_template.geo')

        src = Template(mesh_template.read())
        geofile = src.substitute(d)

        if MPI.rank(MPI.comm_world) == 0:
            with open("meshes/circle-%s"%geom_signature+".geo", 'w') as f:
                f.write(geofile)

            cmd1 = 'gmsh meshes/circle-{}.geo -2 -o meshes/circle-{}.msh'.format(geom_signature, geom_signature)
            cmd2 = 'dolfin-convert -i gmsh meshes/circle-{}.msh meshes/circle-{}.xml'.format(geom_signature, geom_signature)
            
            print('Unable to handle mesh generation at the moment, please generate the mesh and test again.')
            print(cmd1)
            print(cmd2)
            sys.exit()
            print(check_output([cmd1], shell=True))  # run in shell mode in case you are not run in terminal
            Popen([cmd2], stdout=PIPE, shell=True).communicate()

        mesh = Mesh('meshes/circle-{}.xml'.format(geom_signature))
        mesh_xdmf = XDMFFile("meshes/circle-%s.xdmf"%(geom_signature))
        mesh_xdmf.write(mesh)

        # with pygmsh.geo.Geometry() as geom:
        #     circle = geom.add_circle(
        #         [0.0, 0.0, 0.0],
        #         1.0,
        #         mesh_size=0.1,
        #         num_sections=4,
        #         # If compound==False, the section borders have to be points of the
        #         # discretization. If using a compound circle, they don't; gmsh can
        #         # choose by itself where to point the circle points.
        #         compound=True,
        #     )
        #     geom.add_physical(circle.plane_surface, "disk")
        #     # 
        #     mesh = geom.generate_mesh()

        # mesh.write("out.xdmf")
        # mesh.write("out.xml")


        # geom = mshr.Rectangle(dolfin.Point(-Lx/2., -Ly/2.), dolfin.Point(Lx/2., Ly/2.))
        # mesh = mshr.generate_mesh(geom, n * int(float(Lx / ell)))

    print(meshfile)

    mesh_xdmf = dolfin.XDMFFile("meshes/%s-%s.xdmf"%(fname, geom_signature))
    mesh_xdmf.write(mesh)
    if rank == 0: 
        meshf = dolfin.File(os.path.join(outdir, "mesh.xml"))
        meshf << mesh

    V_u = dolfin.VectorFunctionSpace(mesh, "CG", 1)
    V_alpha = dolfin.FunctionSpace(mesh, "CG", 1)
    u = dolfin.Function(V_u, name="Total displacement")
    alpha = dolfin.Function(V_alpha, name="Damage")

    bcs_alpha = []
    # Rectangle
    # bcs_u = [DirichletBC(V_u, Constant((0., 0)), '(near(x[0], %f) or near(x[0], %f))'%(-Lx/2., Lx/2.))]
    # Circle

    bcs_u = [DirichletBC(V_u, Constant((0., 0.)), 'on_boundary')]

    # left = dolfin.CompiledSubDomain("near(x[0], -Lx/2.)", Lx=Lx)
    # right = dolfin.CompiledSubDomain("near(x[0], Lx/2.)", Lx=Lx)
    # bottom = dolfin.CompiledSubDomain("near(x[1],-Ly/2.)", Ly=Ly)
    # top = dolfin.CompiledSubDomain("near(x[1],Ly/2.)", Ly=Ly)

    # mf = dolfin.MeshFunction("size_t", mesh, 1, 0)
    # right.mark(mf, 1)
    # left.mark(mf, 2)
    # bottom.mark(mf, 3)

    state = [u, alpha]

    Z = dolfin.FunctionSpace(mesh, dolfin.MixedElement([u.ufl_element(),alpha.ufl_element()]))
    z = dolfin.Function(Z)

    v, beta = dolfin.split(z)
    dx = dolfin.Measure("dx", metadata=form_compiler_parameters, domain=mesh)
    # ds = dolfin.Measure("ds", subdomain_data=mf)
    ds = dolfin.Measure("ds")

    # Files for output
    file_out = dolfin.XDMFFile(os.path.join(outdir, "output.xdmf"))
    file_eig = dolfin.XDMFFile(os.path.join(outdir, "perturbations.xdmf"))
    file_con = dolfin.XDMFFile(os.path.join(outdir, "continuation.xdmf"))
    file_bif = dolfin.XDMFFile(os.path.join(outdir, "bifurcation_postproc.xdmf"))

    for f in [file_out, file_eig, file_con, file_bif]:
        f.parameters["functions_share_mesh"] = True
        f.parameters["flush_output"] = True

    # Problem definition

    foundation_density = 1./2.*1./ell_e**2.*dot(u, u)
    model = DamagePrestrainedElasticityModel(state, E, nu, ell, sigma_D0,
        user_functional=foundation_density, 
        eps0t=Expression([['t', 0.],[0.,0.]], t=0., degree=0))
    # import pdb; pdb.set_trace()
    model.dx = dx
    model.ds = ds
    energy = model.total_energy_density(u, alpha)*dx
    # Alternate minimization solver
    solver = solvers.AlternateMinimizationSolver(
        energy, [u, alpha], [bcs_u, bcs_alpha], parameters=parameters['alt_min'])

    rP =model.rP(u, alpha, v, beta)*dx + 1/ell_e**2.*dot(v, v)*dx
    rN =model.rN(u, alpha, beta)*dx

    stability = StabilitySolver(mesh, energy, [u, alpha], [bcs_u, bcs_alpha], z, parameters = parameters['stability'])
    # stability = StabilitySolver(mesh, energy, [u, alpha], [bcs_u, bcs_alpha], z, parameters = parameters['stability'], rayleigh=[rP, rN])

    # if isPeriodic:
    #     stability = StabilitySolver(mesh, energy, [u, alpha], [bcs_u, bcs_alpha], z,
    #         parameters = stability_parameters,
    #         constrained_domain = PeriodicBoundary(Lx))
    # else:
    #     stability = StabilitySolver(mesh, energy, [u, alpha], [bcs_u, bcs_alpha], z, parameters = parameters['stability'])

    load_steps = np.linspace(load_min, load_max, parameters['time_stepping']['nsteps'])
    if loads:
        load_steps = loads

    time_data = []

    linesearch = LineSearch(energy, [u, alpha])
    alpha_old = dolfin.Function(alpha.function_space())
    lmbda_min_prev = 0.000001
    bifurcated = False
    bifurcation_loads = []
    save_current_bifurcation = False
    bifurc_count = 0
    alpha_bif = dolfin.Function(V_alpha)
    alpha_bif_old = dolfin.Function(V_alpha)
    bifurcation_loads = []
    for it, load in enumerate(load_steps):
        model.eps0t.t = load
        alpha_old.assign(alpha)
        ColorPrint.print_warn('Solving load t = {:.2f}'.format(load))

        # First order stability conditions
        (time_data_i, am_iter) = solver.solve()

        # Second order stability conditions
        (stable, negev) = stability.solve(solver.problem_alpha.lb)
        ColorPrint.print_pass('Current state is{}stable'.format(' ' if stable else ' un'))

        solver.update()

        #
        mineig = stability.mineig if hasattr(stability, 'mineig') else 0.0
        print('lmbda min', lmbda_min_prev)
        print('mineig', mineig)
        Deltav = (mineig-lmbda_min_prev) if hasattr(stability, 'eigs') else 0

        if (mineig + Deltav)*(lmbda_min_prev+dolfin.DOLFIN_EPS) < 0 and not bifurcated:
            bifurcated = True

            # save 3 bif modes
            print('About to bifurcate load ', load, 'step', it)
            bifurcation_loads.append(load)
            modes = np.where(stability.eigs < 0)[0]

            with file_bif as file:
                leneigs = len(modes)
                maxmodes = min(3, leneigs)
                for n in range(maxmodes):
                    mode = dolfin.project(stability.linsearch[n]['beta_n'], V_alpha)
                    modename = 'beta-%d'%n
                    print(modename)
                    file.write_checkpoint(mode, modename, 0, append=True)

            bifurc_count += 1

        lmbda_min_prev = mineig if hasattr(stability, 'mineig') else 0.

        time_data_i["load"] = load
        time_data_i["stable"] = stable
        time_data_i["dissipated_energy"] = dolfin.assemble(
            model.damage_dissipation_density(alpha)*dx)
        time_data_i["foundation_energy"] = dolfin.assemble(
            1./2.*1/ell_e**2. * dot(u, u)*dx)
        time_data_i["membrane_energy"] = dolfin.assemble(
            model.elastic_energy_density(model.eps(u), alpha)*dx)
        time_data_i["elastic_energy"] = time_data_i["membrane_energy"]+time_data_i["foundation_energy"]
        time_data_i["eigs"] = stability.eigs if hasattr(stability, 'eigs') else np.inf
        time_data_i["stable"] = stability.stable
        time_data_i["# neg ev"] = stability.negev
        # import pdb; pdb.set_trace()

        _sigma = model.stress(model.eps(u), alpha)
        e1 = dolfin.Constant([1, 0])
        _snn = dolfin.dot(dolfin.dot(_sigma, e1), e1)
        time_data_i["sigma"] = 1/Ly * dolfin.assemble(_snn*model.ds(1))

        time_data_i["S(alpha)"] = dolfin.assemble(1./(model.a(alpha))*model.dx)
        time_data_i["A(alpha)"] = dolfin.assemble((model.a(alpha))*model.dx)
        time_data_i["avg_alpha"] = dolfin.assemble(alpha*model.dx)

        ColorPrint.print_pass(
            "Time step {:.4g}: it {:3d}, err_alpha={:.4g}".format(
                time_data_i["load"],
                time_data_i["iterations"],
                time_data_i["alpha_error"]))

        time_data.append(time_data_i)
        time_data_pd = pd.DataFrame(time_data)

        if np.mod(it, savelag) == 0:
            with file_out as f:
                f.write(alpha, load)
                f.write(u, load)
            # with file_out as f:
                f.write_checkpoint(alpha, "alpha-{}".format(it), 0, append = True)
                print('DEBUG: written step ', it)

        if save_current_bifurcation:
            # modes = np.where(stability.eigs < 0)[0]

            time_data_i['h_opt'] = h_opt
            time_data_i['max_h'] = hmax
            time_data_i['min_h'] = hmin

            with file_bif as file:
                # leneigs = len(modes)
                # maxmodes = min(3, leneigs)
                beta0v = dolfin.project(stability.perturbation_beta, V_alpha)
                print('DEBUG: irrev ', alpha.vector()-alpha_old.vector())
                file.write_checkpoint(beta0v, 'beta0', 0, append = True)
                file.write_checkpoint(alpha_bif_old, 'alpha-old', 0, append=True)
                file.write_checkpoint(alpha_bif, 'alpha-bif', 0, append=True)
                file.write_checkpoint(alpha, 'alpha', 0, append=True)

                np.save(os.path.join(outdir, 'energy_perturbations'), energy_perturbations, allow_pickle=True, fix_imports=True)

            with file_eig as file:
                _v = dolfin.project(dolfin.Constant(h_opt)*perturbation_v, V_u)
                _beta = dolfin.project(dolfin.Constant(h_opt)*perturbation_beta, V_alpha)
                _v.rename('perturbation displacement', 'perturbation displacement')
                _beta.rename('perturbation damage', 'perturbation damage')
                # import pdb; pdb.set_trace()
                f.write(_v, load)
                f.write(_beta, load)
                file.write_checkpoint(_v, 'perturbation_v', 0, append=True)
                file.write_checkpoint(_beta, 'perturbation_beta', 0, append=True)

        time_data_pd.to_json(os.path.join(outdir, "time_data.json"))
        # user_postprocess_timestep(alpha, parameters, load, xresol = 100)

    plt.figure()
    dolfin.plot(alpha)
    plt.savefig(os.path.join(outdir, "alpha.png"))
    plt.figure()
    dolfin.plot(u, mode="displacement")
    plt.savefig(os.path.join(outdir, "u.png"))
    _nu = parameters['material']['nu']
    _E = parameters['material']['E']
    _w1 = parameters['material']['sigma_D0']**2. / parameters['material']['E']

    tc = np.sqrt(2*_w1/(_E*(1.-2.*_nu)*(1.+_nu)))
    if parameters['stability']['checkstability']=='True':
        pp.plot_spectrum(parameters, outdir, time_data_pd.sort_values('load'), tc)
    # plt.show()
    print(time_data_pd)
    return time_data_pd

def plot_trace_spectrum(eigendata, parameters, load, outdir):
    nmodes = len(eigendata)
    ell_e = parameters['material']['ell_e']
    ell = parameters['material']['ell']
    fig = plt.figure(figsize=(3*2, nmodes), dpi=80, facecolor='w', edgecolor='k')
    me = eigendata[0]['beta_n'].function_space().mesh()
    X = me.coordinates()
    nel = (max(X[:, 0])-min(X[:, 0]))/((me.hmin()+me.hmax())/2)
    xs = np.linspace(min(X[:, 0]), max(X[:, 0]), nel)
    dx = ((me.hmin()+me.hmax())/2)
    freq = np.fft.fftfreq(xs.shape[-1], d=dx)
    maxlen = 3
    for i,mode in enumerate(eigendata):
        sp = np.fft.fft([mode['beta_n'](x, 0) for x in xs])
        ax = plt.subplot(nmodes, 1, i+1)
        mask = np.where(freq > 0)
        power = np.abs(sp)
        plt.plot(freq[mask]*ell_e, power[mask], label='mode {}'.format(i), c='C1')
        peak_freq = freq[power[mask].argmax()]
        plt.plot(freq[mask]*ell_e, sp.real[mask], label='mode {}'.format(i), c='C3')
        plt.plot(freq[mask]*ell_e, sp.imag[mask], label='mode {}'.format(i), c='C2', lw=.5)
        plt.xlim(0, 3)
        plt.axvline(1/ell_e/2, c='k', lw=.5)
        plt.grid(b=True, which='major', linestyle='-', axis='x')
        plt.box(False)
        ax.axes.yaxis.set_ticks([])
        if i%3 == 0:
            plt.xlabel('$1/\\ell_e$')
        else: ax.axes.xaxis.set_ticks([])
        plt.ylabel('mode {}'.format(i))

        # ax = plt.subplot(nmodes, 2, 2*i+1)
        # if i==0: ax.set_title('Real')
        # plt.plot(freq/ell_e, sp.real, label='mode {}'.format(i), c='C1')
        # # import pdb; pdb.set_trace()
        # plt.xlim(0, maxlen)
        # plt.grid(b=True, which='major', linestyle='-', axis='x')
        # plt.legend()
        # ax.axes.get_yaxis().set_visible(False)
        # plt.box(False)
        # plt.axvline(ell, c='k', ls='dashed')

        # ax = plt.subplot(nmodes, 2, 2*i+2)
        # if i==0: ax.set_title('Imag')
        # plt.plot(freq/ell_e, sp.imag, label='mode {}'.format(i), c='C2')
        # plt.grid(b=True, which='major', linestyle='-', axis='x')
        # plt.legend()
        # plt.axvline(ell, c='k', ls='dashed')
        # ax.axes.get_yaxis().set_visible(False)
        # plt.box(False)
        # # plt.xlim(0, maxlen)

    plt.savefig(os.path.join(outdir, "trace_spectrum-{:3.4f}.pdf".format(load)))
    plt.close(fig)

def plot_energy_slices(eigendata, parameters, u, alpha, model, load, outdir):
    _u = Vector(u.vector())
    _alpha = Vector(alpha.vector())
    ell = parameters['material']['ell']
    w1 = parameters['material']['sigma_D0']**2. / parameters['material']['E']
    en0=assemble(model.total_energy_density(u, alpha)*dx)
    energy = model.total_energy_density(u, alpha)*dx
    energy_diss = model.damage_dissipation_density(alpha)*dx
    energy_elas = model.elastic_energy_density(model.eps(u), alpha)*dx + \
                    model.user_functional*dx
    nmodes = len(eigendata)
    # rows = int(nmodes/2+nmodes%2)
    rows = nmodes
    cols = 2
    fig = plt.figure(figsize=(cols*3,rows*4,), dpi=100, facecolor='w', edgecolor='k')
    for i,mode in enumerate(eigendata):
        plt.subplot(rows, cols, i%cols+1)
        ax = plt.gca()
        hstar = mode['hstar']
        (hmin,hmax) = mode['interval']
        envsu = []
        maxvar = max(abs(hmin), abs(hmax))
        htest = np.linspace(-maxvar, maxvar, 10)
        v_n = mode['v_n']
        beta_n = mode['beta_n']

        en = mode['en_diff']
        # z = np.polyfit(htest, en, mode['order'])
        # p = np.poly1d(z)

        # directional variations. En vs uh
        for h in htest:
            uval = _u[:]     + h*v_n.vector()
            u.vector().set_local(uval)
            envsu.append(assemble(energy)-en0)
        ax.plot(htest, envsu, label='E(u+h $v$, $\\alpha$)', lw=.5)

        ax.axvline(hmin, c='k')
        ax.axvline(hmax, c='k')

        u.vector().set_local(_u[:])
        alpha.vector().set_local(_alpha[:])

        envsa = []
        for h in htest:
            aval = _alpha[:] + h*beta_n.vector()
            alpha.vector().set_local(aval)
            envsa.append(assemble(energy)-en0)
        ax.plot(htest, envsa, label='E(u, $\\alpha$+h $\\beta$)', lw=.5)

        u.vector().set_local(_u[:])
        alpha.vector().set_local(_alpha[:])

        htest = np.linspace(hmin,hmax, mode['order']+1)
        envsh = []
        envsh_diss = []
        envsh_elas = []
        envsh_grad = []
        envsh_ltwo = []
        for h in htest:
            aval = _alpha[:] + h*beta_n.vector()
            uval = _u[:]     + h*v_n.vector()
            alpha.vector().set_local(aval)
            u.vector().set_local(uval)
            envsh.append(assemble(energy)-en0)
            envsh_diss.append(assemble(energy_diss))
            envsh_elas.append(assemble(energy_elas))
            envsh_grad.append(assemble( w1 * ell ** 2 * dot(grad(alpha), grad(alpha))*dx))
            envsh_ltwo.append(assemble(model.w(alpha)*dx))
        ax.plot(htest, envsh, label='$E_h$')
        ax.axvline(hstar)
        ax.axvline(0., c='k', lw=.5, ls=':')
        plt.subplot(rows, cols, i%cols+1+1)
        ax2 = plt.gca()
        # ax2 = ax.twinx()
        # import pdb; pdb.set_trace()
        ax2.plot(htest, np.array(envsh_elas)-min(np.array(envsh_elas)), label='$E_h$ ela', lw=1)
        ax2.plot(htest, np.array(envsh_diss)-min(np.array(envsh_diss)), label='$E_h$ diss', lw=1)
        ax2.plot(htest, np.array(envsh_diss)+np.array(envsh_elas)-min(np.array(envsh_diss)+np.array(envsh_elas)), label='$E_h$ tot')
        ax2.plot(htest, np.array(envsh_grad)-min(np.array(envsh_grad)), label='$grad$ diss', lw=1)
        ax2.plot(htest, np.array(envsh_ltwo)-min(np.array(envsh_ltwo)), label='$ltwo$ diss', lw=1)


        # ax.plot(np.linspace(hmin, hmax, 10), p(np.linspace(hmin, hmax, 10)),
            # label='interp h star = {:.5e}'.format(hstar))

        ax.legend()
        ax2.legend()
    plt.savefig(os.path.join(outdir, "en-{:3.4f}.pdf".format(load)))
    plt.close(fig)

def user_postprocess(self, load):
    # beta_n = self.stability.eigen
    from matplotlib.ticker import StrMethodFormatter
    outdir = self.parameters['outdir']
    alpha = self.solver.alpha

    adm_pert = np.where(np.array([e['en_diff'] for e in stability.eigendata]) < 0)[0]

    fig = plt.figure(figsize=(4, 1.5), dpi=180,)
    ax = plt.gca()
    X =alpha.function_space().tabulate_dof_coordinates()
    xs = np.linspace(min(X[:, 0]),max(X[:, 0]), 300)
    ax.plot(xs, [alpha(x, 0) for x in xs], label='$\\alpha$', lw=1, c='k')
    ax.axhline(0., lw=.5, c='k', ls='-')
    ax3 = ax.twinx()
    ax.legend(fontsize='small')
    # print(stability.eigendata)
    # import pdb; pdb.set_trace()

    for mode in adm_pert:
        beta_n = stability.eigendata[mode]['beta_n']
        ax3.plot(xs, [beta_n(x, 0) for x in xs], label='$\\beta_{}$'.format(mode), ls=':')

    for axi in [ax, ax3]:
        axi.spines['top'].set_visible(False)
        axi.spines['bottom'].set_visible(False)

    ax.get_yaxis().get_major_formatter().set_useOffset(False)
    ax.set_yticks(np.linspace(0, 1, 3))
    ax.yaxis.set_major_formatter(StrMethodFormatter('{x:.1f}')) # 2 decimal places
    plt.xlabel('$x$')
    ax.set_ylabel('$\\alpha$')
    ax3.set_ylabel('$\\beta$')
    ax.set_ylim(0., 1.)
    # ax.set_xlim(-.5, .5)
    ax3.legend(bbox_to_anchor=(0,-.45,1,0.2), loc="lower left", mode="expand", borderaxespad=0, ncol=len(adm_pert), frameon=False)

    fig.savefig(os.path.join(outdir, "profiles-{:.3f}.pdf".format(load)), bbox_inches="tight")

def user_postprocess_timestep(alpha, parameters, load, xresol = 100):
    from matplotlib.ticker import FuncFormatter, MaxNLocator

    # alpha = self.solver.alpha
    # parameters = self.parameters
    xresol = xresol
    X =alpha.function_space().tabulate_dof_coordinates()
    xs = np.linspace(min(X[:, 0]),max(X[:, 0]), xresol)
    # import pdb; pdb.set_trace()

    fig = plt.figure(figsize=(8, 6), dpi=180,)
    alpha0 = [alpha(x, 0) for x in xs]
    spacetime[load] = alpha0
    spacetime = spacetime.fillna(0)
    mat = np.matrix(spacetime)
    plt.imshow(mat, cmap = 'Greys', vmin = 0., vmax = 1., aspect=.1)
    plt.colorbar()

    def format_space(x, pos):
        return '$%1.1f$'%((-x+xresol/2)/xresol)

    def format_time(t, pos):
        return '$%1.1f$'%((t-parameters['load_min'])/parameters['nsteps']*parameters['load_max'])

    ax = plt.gca()

    ax.yaxis.set_major_formatter(FuncFormatter(format_space))
    ax.xaxis.set_major_formatter(FuncFormatter(format_time))

    plt.xlabel('$t$')
    plt.ylabel('$x$')
    fig.savefig(os.path.join(outdir, "spacetime.pdf".format(load)), bbox_inches="tight")

    spacetime.to_json(os.path.join(outdir + "/spacetime.json"))
    pass

if __name__ == "__main__":

    import argparse
    from time import sleep
    from urllib.parse import unquote

    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", required=False,
                        help="JSON configuration string for this experiment")
    parser.add_argument("--ell", type=float, default=0.1)
    parser.add_argument("--ell_e", type=float, default=.3)
    parser.add_argument("--load_max", type=float, default=3.0)
    parser.add_argument("--load_min", type=float, default=0.)
    parser.add_argument("--Lx", type=float, default=1)
    parser.add_argument("--Ly", type=float, default=0.1)
    parser.add_argument("--n", type=int, default=2)
    parser.add_argument("--nu", type=float, default=0.0)
    parser.add_argument("--nsteps", type=int, default=30)
    parser.add_argument("--degree", type=int, default=2)
    parser.add_argument("--postfix", type=str, default='')
    parser.add_argument("--outdir", type=str, default=None)
    parser.add_argument("--savelag", type=int, default=1)
    parser.add_argument("--E", type=float, default=1)
    parser.add_argument("--parameters", type=str, default=None)
    parser.add_argument("--print", type=bool, default=False)
    parser.add_argument("--continuation", type=bool, default=False)
    parser.add_argument("--test", type=bool, default=True)
    parser.add_argument("--periodic", action='store_true')
    # args = parser.parse_args()
    args, unknown = parser.parse_known_args()
    if len(unknown):
        ColorPrint.print_warn('Unrecognised arguments:')
        print(unknown)
        ColorPrint.print_warn('continuing in 5s')
        sleep(5)
    # signature = md5().hexdigest()
    # import pdb; pdb.set_trace()
    if args.outdir == None:
        args.postfix += '-cont' if args.continuation==True else ''
        outdir = "../output/{:s}".format('film')
    else:
        outdir = args.outdir

    if args.print and args.parameters is not None:
        cmd = ''
        with open(args.parameters, 'r') as params:
            parameters = json.load(params)
            for k,v in parameters.items():
                for c,u in v.items():
                    cmd = cmd + '--{} {} '.format(c, str(u))
        print(cmd)
        sys.exit()

    config = '{}'
    if args.config:
        config = unquote(args.config).replace('\'', '"')

    # import pdb; pdb.set_trace()
    if args.parameters is not None:
        experiment = ''
        with open(args.parameters, 'r') as params:
            config = str(json.load(params))
        config = unquote(config).replace('\'', '"')
        config = config.replace('"load"', '"time_stepping"')
        print(config)
        traction_test(configString=config)
    else:
        traction_test(
            ell=args.ell,
            ell_e=args.ell_e,
            load_min=args.load_min,
            load_max=args.load_max,
            nsteps=args.nsteps,
            n=args.n,
            Lx=args.Lx,
            Ly=args.Ly,
            outdir=outdir,
            postfix=args.postfix,
            savelag=args.savelag,
            continuation=args.continuation,
            periodic=args.periodic,
            configString=config,
            test=args.test
        )



