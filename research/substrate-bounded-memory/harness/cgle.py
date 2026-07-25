"""2D Complex Ginzburg-Landau — pseudo-spectral ETD2 integrator + vortex tooling.

D-036 substrate-as-bounded-memory. No LLM anywhere in this module.

Equation (sealed in PREREG.md):
    dA/dt = A + (1 + i b) lap(A) - (1 + i c) |A|^2 A      (periodic BCs)

Fourier: linear operator L(k) = 1 - (1 + i b) k^2  (diagonal), nonlinear
N(A) = -(1 + i c) |A|^2 A. Time-stepped with the Cox-Matthews ETD2
exponential Adams-Bashforth scheme. On this grid |L| is bounded away from 0
(min |L| ~ 0.5 at k^2=1 for b=0.5), so the ETD coefficients need no
contour-averaging fix.
"""
from __future__ import annotations

import numpy as np


class CGLE:
    def __init__(self, b: float, c: float, N: int = 256, side: float = 128.0,
                 dt: float = 0.05, seed: int | None = None):
        self.b = float(b)
        self.c = float(c)
        self.N = int(N)
        self.side = float(side)
        self.dx = side / N
        self.dt = float(dt)
        self.rng = np.random.default_rng(seed)

        # wavenumbers (periodic box of physical length `side`)
        k1 = 2.0 * np.pi * np.fft.fftfreq(N, d=self.dx)
        kx, ky = np.meshgrid(k1, k1, indexing="ij")
        k2 = kx**2 + ky**2

        L = 1.0 - (1.0 + 1j * self.b) * k2            # linear operator, diagonal in k
        h = self.dt
        E = np.exp(L * h)
        self.L = L
        self.E = E
        # Cox-Matthews ETD2 (exponential Adams-Bashforth, 2nd order)
        L2 = L * L
        self.c0 = (E - 1.0) / L                                   # ETD1 first step (N_n)
        self.c1 = ((1.0 + h * L) * E - 1.0 - 2.0 * h * L) / (h * L2)   # N_n
        self.c2 = (-E + 1.0 + h * L) / (h * L2)                        # N_{n-1}

        self.A = None
        self._Nprev_hat = None  # previous nonlinear term (Fourier), for the AB2 step

    # -- field setup ------------------------------------------------------
    def coord_grids(self):
        ax = (np.arange(self.N) + 0.5) * self.dx   # cell centres, physical units
        X, Y = np.meshgrid(ax, ax, indexing="ij")
        return X, Y

    def seed_vortices(self, centres, charges, r_core: float = 2.0, n_img: int = 2):
        """Seed a NET-NEUTRAL vortex set with a periodic phase (no boundary seams).

        Each vortex's atan2 phase is summed over an (2*n_img+1)^2 tiling of
        periodic images. For a net-neutral set the image sum converges (dipole
        far field) and the total exp(i*theta) is periodic to high accuracy, which
        the single-image atan2 sum is not (its branch cuts hit the box edge and
        nucleate spurious defects at the seam). |A| is a product of tanh cores at
        the min-image distance; the CGLE relaxes the exact core profile within
        O(1) time — only the phase topology must start correct.

        `centres` physical (x,y); `charges` in {+1,-1}; must sum to 0.
        """
        centres = list(centres)
        charges = list(charges)
        if sum(charges) != 0:
            raise ValueError("seed_vortices requires a net-neutral charge set "
                             "(periodic BCs force total winding 0)")
        X, Y = self.coord_grids()
        S = self.side
        shifts = [(a * S, b * S) for a in range(-n_img, n_img + 1)
                  for b in range(-n_img, n_img + 1)]
        phase = np.zeros((self.N, self.N))
        amp = np.ones((self.N, self.N))
        for (x0, y0), s in zip(centres, charges):
            ph = np.zeros((self.N, self.N))
            for (sx, sy) in shifts:
                ph += np.arctan2(Y - (y0 + sy), X - (x0 + sx))
            phase += s * ph
            ddx = X - x0; ddy = Y - y0
            ddx -= S * np.round(ddx / S); ddy -= S * np.round(ddy / S)
            amp *= np.tanh(np.sqrt(ddx * ddx + ddy * ddy) / r_core)
        self.A = amp * np.exp(1j * phase)
        self._Nprev_hat = None
        return self.A

    # -- time stepping ----------------------------------------------------
    def _Nhat(self, A):
        return np.fft.fft2(-(1.0 + 1j * self.c) * (np.abs(A) ** 2) * A)

    def step(self):
        A = self.A
        Ahat = np.fft.fft2(A)
        Nhat = self._Nhat(A)
        if self._Nprev_hat is None:
            Ahat_new = self.E * Ahat + self.c0 * Nhat            # ETD1 bootstrap
        else:
            Ahat_new = self.E * Ahat + self.c1 * Nhat + self.c2 * self._Nprev_hat
        self._Nprev_hat = Nhat
        self.A = np.fft.ifft2(Ahat_new)
        return self.A

    def evolve(self, n_steps: int, report_every: int | None = None, report=None):
        for i in range(n_steps):
            self.step()
            if report_every and report is not None and (i + 1) % report_every == 0:
                report(i + 1, self.A)
        return self.A

    # -- defect detection -------------------------------------------------
    def find_defects(self):
        """Locate topological defects by phase winding around each plaquette.

        Returns (positions_physical [M,2], charges [M]). A defect sits at a
        plaquette whose summed phase winding is +/-2*pi.
        """
        th = np.angle(self.A)
        # winding around the 2x2 plaquette (i,j)->(i+1,j)->(i+1,j+1)->(i,j+1)
        def d(a, b):
            return np.angle(np.exp(1j * (a - b)))  # wrapped difference in (-pi,pi]
        thr = np.roll(th, -1, axis=0)   # i+1, j
        thur = np.roll(thr, -1, axis=1)  # i+1, j+1
        thu = np.roll(th, -1, axis=1)   # i, j+1
        w = d(thr, th) + d(thur, thr) + d(thu, thur) + d(th, thu)
        winding = np.round(w / (2.0 * np.pi)).astype(int)
        ii, jj = np.nonzero(winding != 0)
        charges = winding[ii, jj]
        # plaquette centre in physical units
        xs = (ii + 1.0) * self.dx
        ys = (jj + 1.0) * self.dx
        pos = np.stack([xs, ys], axis=1)
        return pos, charges

    def defect_count(self):
        pos, ch = self.find_defects()
        return len(ch)
