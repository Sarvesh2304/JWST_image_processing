"""Idealised exposure-time estimates behind the hardware configurations in 04-observatory.md.
Assumptions: Bessell V, ~1000 photons/s/cm^2/A at V=0 over 880 A; aperture radius = 1 FWHM;
Gaussian PSF; scintillation from Young (1967) scaled by 1.5 (Osborn et al. 2015). Ignores flat-field
errors, comparison-star noise and red noise, which typically add 1-3 mmag in practice."""
import numpy as np
# V-band photon flux for V=0: ~1000 photons/s/cm^2/A * 880 A (Bessell V FWHM)
PH0 = 1000*880.0
def config(name, D_cm, obstr, f_mm, pix_um, qe, thr, rn, seeing, sqm, dark=0.002, h_m=200, X=1.3):
    area = np.pi*(D_cm/2)**2*(1-obstr**2)
    zp_e = PH0*area*qe*thr                      # e-/s for V=0
    scale = 206.265*pix_um/f_mm                 # arcsec/px
    fwhm_px = seeing/scale
    r_ap = 1.0*fwhm_px                          # aperture radius ~1 FWHM (near optimal)
    npix = np.pi*r_ap**2
    ee = 1-np.exp(-4*np.log(2)*(r_ap/fwhm_px)**2)  # Gaussian enclosed fraction within r
    sky = zp_e*10**(-0.4*sqm)*scale**2          # e-/s/px
    def snr(m, t):
        S = zp_e*10**(-0.4*m)*ee*t
        return S/np.sqrt(S + npix*(sky*t + dark*t + rn**2))
    def lim(t, k=5):
        ms=np.linspace(8,25,5000); s=snr(ms,t); return ms[np.argmin(abs(s-k))]
    # scintillation (Young 1967), Osborn+2015 suggest ~1.5x larger
    def scint(t): return 1.5*0.09*D_cm**(-2/3)*X**1.75*np.exp(-h_m/8000)*(2*t)**-0.5
    print(f"{name}: D={D_cm}cm f={f_mm}mm scale={scale:.2f}\"/px ZP(V=0)={zp_e:.2e} e-/s sky={sky:.2f} e-/s/px")
    for t in (60,300):
        print(f"   t={t}s: 5-sigma V_lim={lim(t):.1f}; S/N=100 at V={lim(t,100):.1f}; scint(1.5xYoung)={1000*scint(t):.1f} mmag")
    # precision for a V=12 star in 60s (photon+sky+rn) and with scintillation
    m=12; t=60; s=snr(m,t); ph=1.0857/s; sc=scint(t)
    print(f"   V=12, 60s: photon-limited {1000*ph:.1f} mmag, + scintillation -> {1000*np.hypot(ph,sc):.1f} mmag")
for args in [("A 200mm f/4 Newtonian, IMX571-class 3.76um", 20,0.33,800,3.76,0.8,0.65,1.5,2.5,20.0),
             ("A' 100mm f/6 APO refractor", 10,0.0,600,3.76,0.8,0.75,1.5,2.5,20.0),
             ("B 280mm f/7 corrected SCT, bin2 (7.52um)", 28,0.37,1960,7.52,0.8,0.6,2.1,2.5,20.5),
             ("C 430mm f/6.8 CDK, 9um pixels", 43,0.48,2920,9.0,0.8,0.6,2.0,2.0,21.0)]:
    config(*args)
