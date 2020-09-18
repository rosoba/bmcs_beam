from scipy.optimize import newton, brentq, root

import matplotlib.pyplot as plt
import numpy as np
import sympy as sp
import traits.api as tr


# For info (left is the notation in Mobasher paper, right is notation in this file):
# ------------------------------------------------------------------
# E = E_ct
# E_c = E_cc
# E_s = E_j
# eps_cr = eps_cr
# eps_cu = eps_cu
# eps_tu = eps_tu
# eps_cy = eps_cy
# mu = mu

# gamma = E_cc/E_ct
# omega = eps_cy/eps_cr
# lambda_cu = eps_cu/eps_cr
# beta_tu = eps_tu/eps_cr
# psi = eps_sy_j/eps_cr
# n = E_j/E_ct
# alpha = z_j/h

# r = A_s_c/A_s_t

# rho_g = A_j[0]/A_c # where A_j[0] must be tension steel area
# ------------------------------------------------------------------

class ModelData(tr.HasStrictTraits):
    # Concrete
    E_ct = tr.Float(24000)            # E modulus of concrete on tension
    E_cc = tr.Float(25000)            # E modulus of concrete on compression
    eps_cr = tr.Float(0.001)          # Concrete cracking strain
    eps_cy = tr.Float(-0.003)         # Concrete compressive yield strain
    eps_cu = tr.Float(-0.01)          # Ultimate concrete compressive strain
    eps_tu = tr.Float(0.003)          # Ultimate concrete tensile strain
    mu = tr.Float(0.33)               # Post crack tensile strength parameter (represents how much strength is left
                                      # after the crack because of short steel fibers in the mixture)

    # Reinforcement
    z_j = tr.Array(np.float_, value=[10])                           # z positions of reinforcement layers
    A_j = tr.Array(np.float_, value=[[np.pi * (16 / 2.) ** 2]])     # cross section area of reinforcement layers
    E_j = tr.Array(np.float_, value=[[210000]])                     # E modulus of reinforcement layers
    eps_sy_j = tr.Array(np.float_, value=[[500. / 210000.]])        # Steel yield strain


class MomentCurvatureSymbolic(tr.HasStrictTraits):
    """"This class handles all the symbolic calculations so that the class MomentCurvature doesn't use sympy ever"""

    # Sympy symbols definition
    E_ct, E_cc, eps_cr, eps_tu, mu = sp.symbols(r'E_ct, E_cc, varepsilon_cr, varepsilon_tu, mu', real=True,
                                                nonnegative=True)
    eps_cy, eps_cu = sp.symbols(r'varepsilon_cy, varepsilon_cu', real=True, nonpositive=True)
    kappa = sp.Symbol('kappa', real=True, nonpositive=True)
    eps_top = sp.symbols('varepsilon_top', real=True, nonpositive=True)
    eps_bot = sp.symbols('varepsilon_bot', real=True, nonnegative=True)
    b, h, z = sp.symbols('b, h, z', nonnegative=True)
    eps_sy, E_s = sp.symbols('varepsilon_sy, E_s')
    eps = sp.Symbol('varepsilon', real=True)

    eps_z_ = tr.Any
    subs_eps = tr.Any
    sig_c_z_lin = tr.Any
    sig_s_eps = tr.Any
    subs_eps = tr.Any

    model_data = tr.Instance(ModelData)

    def _model_data_default(self):
        return ModelData()

    model_params = tr.Property

    def _get_model_params(self):
        return {
            self.E_ct: self.model_data.E_ct,
            self.E_cc: self.model_data.E_cc,
            self.eps_cr: self.model_data.eps_cr,
            self.eps_cy: self.model_data.eps_cy,
            self.eps_cu: self.model_data.eps_cu,
            self.mu: self.model_data.mu,
            self.eps_tu: self.model_data.eps_tu
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Linear profile of strain over the cross section height
        self.eps_z_ = self.eps_bot + self.z * (self.eps_top - self.eps_bot) / self.h

        # Express varepsilon_top as a function of kappa and varepsilon_bot
        curvature_definition_ = self.kappa + self.eps_z_.diff(self.z)
        self.subs_eps = {self.eps_top: sp.solve(curvature_definition_, self.eps_top)[0]}
        # to return eps on a value z when (kappa, eps_bot) are given
        # get_eps_z = sp.lambdify((kappa, eps_bot, z), eps_z_.subs(subs_eps), 'numpy')

        # Concrete constitutive law
        sig_c_eps = sp.Piecewise(
            (0, self.eps < self.eps_cu),
            (self.E_cc * self.eps_cy, self.eps < self.eps_cy),
            (self.E_cc * self.eps, self.eps < 0),
            (self.E_ct * self.eps, self.eps < self.eps_cr),
            (self.mu * self.E_ct * self.eps_cr, self.eps < self.eps_tu),
            (0, self.eps >= self.eps_tu)
        )

        # Stress over the cross section height
        sig_c_z = sig_c_eps.subs(self.eps, self.eps_z_)

        # Substitute eps_top to get sig as a function of (kappa, eps_bot, z)
        self.sig_c_z_lin = sig_c_z.subs(self.subs_eps)

        # Reinforcement constitutive law
        self.sig_s_eps = sp.Piecewise(
            (-self.E_s * self.eps_sy, self.eps < -self.eps_sy),
            (self.E_s * self.eps, self.eps < self.eps_sy),
            (self.E_s * self.eps_sy, self.eps >= self.eps_sy)
        )

    b_z = tr.Any
    get_b_z = tr.Property

    @tr.cached_property
    def _get_get_b_z(self):
        return sp.lambdify(self.z, self.b_z, 'numpy')


    # get_eps_z = tr.Property(depends_on='model_params_items')
    get_eps_z = tr.Property()

    @tr.cached_property
    def _get_get_eps_z(self):
        return sp.lambdify((self.kappa, self.eps_bot, self.z), self.eps_z_.subs(self.subs_eps), 'numpy')

    get_sig_c_z = tr.Property(depends_on='model_params_items')

    @tr.cached_property
    def _get_get_sig_c_z(self):
        return sp.lambdify((self.kappa, self.eps_bot, self.z), self.sig_c_z_lin.subs(self.model_params), 'numpy')

    # get_sig_s_eps = tr.Property(depends_on='model_params_items')
    get_sig_s_eps = tr.Property()

    @tr.cached_property
    def _get_get_sig_s_eps(self):
        return sp.lambdify((self.eps, self.E_s, self.eps_sy), self.sig_s_eps, 'numpy')


class MomentCurvature(tr.HasStrictTraits):
    """Class returning the moment curvature relationship."""

    mcs = tr.Instance(MomentCurvatureSymbolic)

    def _mcs_default(self):
        return MomentCurvatureSymbolic()

    h = tr.Float

    model_params = tr.DelegatesTo('mcs')
    model_data = tr.DelegatesTo('mcs')

    # Number of material points along the height of the cross section
    n_m = tr.Int(100)

    z_m = tr.Property(depends_on='n_m, h')

    @tr.cached_property
    def _get_z_m(self):
        return np.linspace(0, self.h, self.n_m)

    kappa_range = tr.Tuple(-0.001, 0.001, 101)

    kappa_t = tr.Property(tr.Array(np.float_), depends_on='kappa_range')

    @tr.cached_property
    def _get_kappa_t(self):
        return np.linspace(*self.kappa_range)

    # Normal force
    def get_N_s_tj(self, kappa_t, eps_bot_t):
        eps_z_tj = self.mcs.get_eps_z(kappa_t[:, np.newaxis], eps_bot_t[:, np.newaxis], self.model_data.z_j[np.newaxis, :])
        sig_s_tj = self.mcs.get_sig_s_eps(eps_z_tj, self.model_data.E_j, self.model_data.eps_sy_j)
        return np.einsum('j,tj->tj', self.model_data.A_j, sig_s_tj)

    def get_N_c_t(self, kappa_t, eps_bot_t):
        z_tm = self.z_m[np.newaxis, :]
        b_z_m = self.mcs.get_b_z(z_tm)  # self.get_b_z(self.z_m) also OK
        N_z_tm = b_z_m * self.mcs.get_sig_c_z(kappa_t[:, np.newaxis], eps_bot_t[:, np.newaxis], z_tm)
        return np.trapz(N_z_tm, x=z_tm, axis=-1)

    def get_N_t(self, kappa_t, eps_bot_t):
        N_s_t = np.sum(self.get_N_s_tj(kappa_t, eps_bot_t), axis=-1)
        return self.get_N_c_t(kappa_t, eps_bot_t) + N_s_t

    # SOLVER: Get eps_bot to render zero force

    eps_bot_t = tr.Property()
    r'''Resolve the tensile strain to get zero normal force 
    for the prescribed curvature
    '''

    def _get_eps_bot_t(self):
        res = root(lambda eps_bot_t: self.get_N_t(self.kappa_t, eps_bot_t),
                   0.0000001 + np.zeros_like(self.kappa_t), tol=1e-6)
        return res.x

    # POSTPROCESSING

    eps_cr = tr.Property()

    def _get_eps_cr(self):
        return np.array([self.model_data.eps_cr], dtype=np.float_)

    kappa_cr = tr.Property()

    def _get_kappa_cr(self):
        res = root(lambda kappa: self.get_N_t(kappa, self.eps_cr), 0.0000001 + np.zeros_like(self.eps_cr), tol=1e-10)
        return res.x

    # Bending moment

    M_s_t = tr.Property()

    def _get_M_s_t(self):
        eps_z_tj = self.mcs.get_eps_z(self.kappa_t[:, np.newaxis], self.eps_bot_t[:, np.newaxis],
                                      self.model_data.z_j[np.newaxis, :])
        sig_z_tj = self.mcs.get_sig_s_eps(eps_z_tj, self.model_data.E_j, self.model_data.eps_sy_j)
        return -np.einsum('j,tj,j->t', self.model_data.A_j, sig_z_tj, self.model_data.z_j)

    M_c_t = tr.Property()

    def _get_M_c_t(self):
        z_tm = self.z_m[np.newaxis, :]
        b_z_m = self.mcs.get_b_z(z_tm)
        N_z_tm = b_z_m * self.mcs.get_sig_c_z(self.kappa_t[:, np.newaxis], self.eps_bot_t[:, np.newaxis], z_tm)
        return -np.trapz(N_z_tm * z_tm, x=z_tm, axis=-1)

    M_t = tr.Property()

    def _get_M_t(self):
        return self.M_c_t + self.M_s_t

    N_s_tj = tr.Property()

    def _get_N_s_tj(self):
        return self.get_N_s_tj(self.kappa_t, self.eps_bot_t)

    eps_tm = tr.Property()

    def _get_eps_tm(self):
        return self.get_eps_z(self.kappa_t[:, np.newaxis], self.eps_bot_t[:, np.newaxis], self.z_m[np.newaxis, :])

    sig_tm = tr.Property()

    def _get_sig_tm(self):
        return self.mcs.get_sig_c_z(self.kappa_t[:, np.newaxis], self.eps_bot_t[:, np.newaxis],self.z_m[np.newaxis, :])

    idx = tr.Int(0)

    M_norm = tr.Property()

    def _get_M_norm(self):
        # Section modulus @TODO optimize W for var b
        W = (self.b * self.h ** 2) / 6
        sig_cr = self.model_data.E_ct * self.model_data.eps_cr
        return W * sig_cr

    kappa_norm = tr.Property()

    def _get_kappa_norm(self):
        return self.kappa_cr

    def get_kappa(self, M):
        '''cut off the descending tails
        '''
        I_M = np.where(self.M_t[1:] - self.M_t[:-1] > 0)
        M_I = self.M_t[I_M]
        kappa_I = self.kappa_t[I_M]
        return np.interp(M, M_I, kappa_I)

    def plot_norm(self, ax1, ax2):
        idx = self.idx
        ax1.plot(self.kappa_t / self.kappa_norm, self.M_t / self.M_norm)
        ax1.plot(self.kappa_t[idx] / self.kappa_norm, self.M_t[idx] / self.M_norm, marker='o')
        ax2.barh(self.z_j, self.N_s_tj[idx, :], height=2, color='red', align='center')
        # ax2.fill_between(eps_z_arr[idx,:], z_arr, 0, alpha=0.1);
        ax3 = ax2.twiny()
        #        ax3.plot(self.eps_tm[idx, :], self.z_m, color='k', linewidth=0.8)
        ax3.plot(self.sig_tm[idx, :], self.z_m)
        ax3.axvline(0, linewidth=0.8, color='k')
        ax3.fill_betweenx(self.z_m, self.sig_tm[idx, :], 0, alpha=0.1)
        self._align_xaxis(ax2, ax3)

    M_scale = tr.Float(1e+6)

    def plot(self, ax1, ax2):
        idx = self.idx
        ax1.plot(self.kappa_t, self.M_t / self.M_scale)
        ax1.set_ylabel('Moment [kN.m]')
        ax1.set_xlabel('Curvature [$m^{-1}$]')
        ax1.plot(self.kappa_t[idx], self.M_t[idx] / self.M_scale, marker='o')
        ax2.barh(self.model_data.z_j, self.N_s_tj[idx, :], height=6, color='red', align='center')
        # ax2.plot(self.N_s_tj[idx, :], self.z_j, color='red')
        # print('Z', self.z_j)
        # print(self.N_s_tj[idx, :])
        # ax2.fill_between(eps_z_arr[idx,:], z_arr, 0, alpha=0.1);
        ax3 = ax2.twiny()
        #        ax3.plot(self.eps_tm[idx, :], self.z_m, color='k', linewidth=0.8)
        ax3.plot(self.sig_tm[idx, :], self.z_m)
        ax3.axvline(0, linewidth=0.8, color='k')
        ax3.fill_betweenx(self.z_m, self.sig_tm[idx, :], 0, alpha=0.1)
        self._align_xaxis(ax2, ax3)

    def _align_xaxis(self, ax1, ax2):
        """Align zeros of the two axes, zooming them out by same ratio"""
        axes = (ax1, ax2)
        extrema = [ax.get_xlim() for ax in axes]
        tops = [extr[1] / (extr[1] - extr[0]) for extr in extrema]
        # Ensure that plots (intervals) are ordered bottom to top:
        if tops[0] > tops[1]:
            axes, extrema, tops = [list(reversed(l)) for l in (axes, extrema, tops)]

        # How much would the plot overflow if we kept current zoom levels?
        tot_span = tops[1] + 1 - tops[0]

        b_new_t = extrema[0][0] + tot_span * (extrema[0][1] - extrema[0][0])
        t_new_b = extrema[1][1] - tot_span * (extrema[1][1] - extrema[1][0])
        axes[0].set_xlim(extrema[0][0], b_new_t)
        axes[1].set_xlim(t_new_b, extrema[1][1])


if __name__ == '__main__':
    # Parameters entry
    # (Values from parametric study in paper p.11 to draw Fig. 7)
    z = sp.Symbol('z')

    E_ct_ = 24000
    eps_cr_ = 0.000125
    gamma_ = 1
    omega_ = 8.5
    lambda_cu_ = 28
    beta_tu_ = 160
    psi_ = 16
    n_ = 8.75
    alpha_ = 0.9

    mu_ = 0.33
    rho_g_ = 0.003

    # not given in paper
    r_ = 0.0

    h_ = 666
    zeta = 0.15  # WHY USING 0.15, 0.2 ... gives wrong results!!!
    b_w = 50  # o = 0.1
    b_f = 500
    h_w = (1 - zeta) * h_

    # Substituting formulas:
    E_cc_ = gamma_ * E_ct_
    eps_cy_ = omega_ * eps_cr_
    eps_cu_ = lambda_cu_ * eps_cr_
    eps_tu_ = beta_tu_ * eps_cr_
    eps_sy_j_ = np.array([psi_ * eps_cr_, psi_ * eps_cr_])
    E_j_ = np.array([n_ * E_ct_, n_ * E_ct_])
    z_j_ = np.array([h_ * (1 - alpha_), alpha_ * h_])

    # Defining a variable b
    b_z_ = sp.Piecewise(
        (b_w, z < h_w),
        (b_f, z >= h_w)
    )

    A_c_ = sp.integrate(b_z_, (z, 0, h_))
    A_s_t_ = rho_g_ * A_c_
    A_s_c_ = r_ * A_s_t_
    A_j_ = np.array([A_s_t_, A_s_c_])  # A_j[0] must be tension steel area

    ''' Creating MomentCurvature object '''

    mc = MomentCurvature(idx=25, n_m=100)
    mc.h = h_
    # mc.b_z = b_z_
    # mc.model_params = {E_ct: E_ct_,
    #                    E_cc: E_cc_,
    #                    eps_cr: eps_cr_,
    #                    eps_cy: eps_cy_,
    #                    eps_cu: eps_cu_,
    #                    mu: mu_,
    #                    eps_tu: eps_tu_}

    mc.mcs.b_z = b_z_

    model_data = ModelData()
    model_data.E_ct = E_ct_
    model_data.E_cc = E_cc_
    model_data.eps_cr = eps_cr_
    model_data.eps_cy = eps_cy_
    model_data.eps_cu = eps_cu_
    model_data.mu = mu_
    model_data.eps_tu = eps_tu_

    model_data.z_j = z_j_
    model_data.A_j = A_j_
    model_data.E_j = E_j_

    mc.model_data = model_data

    # mc.z_j = z_j_
    # mc.A_j = A_j_
    # mc.E_j = E_j_

    if True:
        # If plot_norm is used, use the following:
        # mc.kappa_range = (0, mc.kappa_cr * 100, 100)

        mc.kappa_range = (-0.00002, 0.00002, 100)

        # print('XXX', mc.kappa_cr)

        # Plotting
        fig, ((ax1, ax2)) = plt.subplots(1, 2, figsize=(10, 5))
        mc.plot(ax1, ax2)
        plt.show()

    # mc = MomentCurvature(idx=25, n_m=100)
    #
    # M_range = np.linspace(-40, 70, 100)
    # kappa = mc.get_kappa(M_range * 1e+6)
    # print(kappa)
    #
    # fig, ((ax1, ax2)) = plt.subplots(1, 2, figsize=(10, 5))
    # mc.plot(ax1, ax2)
    # plt.show()
    #
    # # Plotting
    # fig, ax1 = plt.subplots(1, 1, figsize=(10, 5))
    # plt.plot(M_range, kappa)
    # plt.show()
