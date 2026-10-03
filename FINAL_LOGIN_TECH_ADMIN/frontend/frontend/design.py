"""
frontend/design.py - Centrum Laboratory | the dashboard design (CSS + logo)

DESIGN_CSS is the stylesheet of the original admin/technician HTML design and
TEACHER_CSS holds the few rules that only the teacher design had. The
dashboards build their screens from the same class names, so they look like
the HTML design. STREAMLIT_CSS (in ui.py) fits Streamlit's own widgets into it.
"""

LOGO_URI = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAOIAAAA+CAYAAAA27MeDAAAYbklEQVR4nO2deXwUVbbHv9VJupskne7sCYSQheyBLCQQARVBkGFRFEZAR0bccBx8io7im3Fm3nMcRx0dN0RxwQVFXBBBQUY2UXYIIfsKWchOyB6600lXvT+q0+kmoOLwMCT1/Xzqk07dqq5blf7lnHvOubcFSZIkFBQUflFUv3QHFBQUFCEqKPQLFCEqKPQDFCEqKPQDFCEqKPQDFCEqKPQDFCEqKPQDFCEqKPQDFCEqKPQDnH/pDvRHzN1QUWPhYFY32cUWSistlFRYaGqVi5DchggE+asIC3IiIdqJ5Bhnwoc74ekh/MI9V7hcEZQSNxlzN1RUW9i6x8xX33VRUSNi6pQfjSRJCMIPi8zTQ2B8kjPXT1KTEueMp4fibCj8dAa9EM3dkFXYzeoNJr493G0Tn4wAOD6eHxalBJKIwUPimlQX5kzWEh+pVkSp8KMMWiF2dUNmYTerN3Ty7eGuswTYKzhBEOh5ROcSoSSJgAiSdcOCJFqQJAsgEjbcmVtneTBzko5AX5dLc3MKlx2DUoilVRbeXm9iw44ujJ3nvn0J2R7CuQQoygKURLAKDklEkqwC7BGk9bUkiXjqBW6Z5c29CwMweChDcwVHBuUnIsjPiZlXqSmvEdmb0W0TmoPg7JQo73IUn2QToKV3P6JVfGcLUiTY35Wxo90VESqck0FpEXsoKrewYq2Jr3abz9EqAZJVZBabxesVmywy236pV4S9opX3TxijZ/mSEJLjPS7p/SlcPgwaIRaVW1i9wUR3N9y3YAhhQXIApcMosX67mZfWGGlqFa3jwR4RydZMkkQEe2tnFaC9xbO3hIJViGoXuDLFkwcXh5Acr/9F71+hfzMo/KQOo8SuQ118slW2fDnFFpbeomXW1WrchgjMvVaNn6fAW5+1k55rsgvAWGzjPgm7MaEkWn/vaRcRbBZT/t3FReL6KQEsvzeSoX7aS3KfhcWl7N5zECeVijFJ8URHhqPVai7JtRX+Mwa8Rezqho27zPzjzTO2hDySiOsQkZumaFi2yB1PvWwdc4rNvPBeI9v3tVtdTIvNxewdE4p2bqqjNewRr5urigWzh/PQnVF46i9NpLStvYOVb3zAcy++CcDsGVP482NLCQ0Zfkmur/CfMeATXDkl3Wzc2WkTofx/R6LjjIU1m1q57bE6tu87A0B8hJrnHvXlv+82oNd1I1pMSKIJSeyUN0unbR/W3yX7YyyduGlFFswaykN3Rl4yESpc/gxo17S5VWL34W6HyChINjdTkkRyirt44Ckjc6e6s+x2bzz1TvzmBi+8DLDi/UpOVJw5a4woItpHRulNYbi5OjF/9nAeuisaT70aALO5i4Li4xw8lElTcwtengbi4yKJigjF0+A4bjSbzZxqaKSurgGDwYOw0GDMZjOV1XUczcihsrqOsJDhpCaPIjDQz3ZeW3sHJ0/W0Nzc6rivsgZnZ2d07m4YDHKg6PTpJsoqqnBxcWZ40FBcXbUcy8onIzOP0JAgxo5JwNPgQcPpJsorqpBEiaBhAQQE+Dr0ta2tg4rKapqbWxk21J+QEUG2toaGRspPVuPi4kLw8KEY9Dqqqmo5fDSb2voGfH28SEmKZ0TwMNs5lVW17D2QTm3dKcJDR5CaPAp/f5+L80G4DBjQrunm78z8ZYWdS4rU60ZK3UhSt904r5tRI9Usu92PayfIH9rsgjaef+sEmQUtpIzSMy7BwMRUb0KGudJtETle0cbBjAZ27KmisrqNG64L5r8Wx6PVOgGQl1/MK6+9z1dbd2EymRz6FhcTwcMP3MXsGVNs+4pKynhhxdt89vnXJCXGcdvCGzlZWc27az6jyU5k8XGR/OGBu5g5fTJms5nX31rL355ecd7nMD4tmeUP38v4ccm8/tZa/vzEv9C5u7Ho1rn4eBt4aeW7NDe3EhoynGVLF3PVxHG89Oo7vLPmMwDmz53J448tJcC/V4yvrlrD//z9JQCmTBrPY3/4HYmjY6iqruWFV1bz3oefExY6nLsXL0AlqFj55geUV1TZzk8cHcsjy+4mLTWJD9Z9wco3PqCuvsHWnpQQyyPL7mHq5IkX8ie/bBmwFrGs2sJ36V00tUq91lCS7PKAvVax53V2UQf3P3GCedM9eeiOYYyK1vHucwnnuYKKhBhPEmI8ueeWCMxdIqJFtInw4OFMnn7+NfbsO3LOs3Pzi3n+pbcAHMTYQ0VFFf984Q1qauv7tOXkFvHKa++j1WoZm5KA0dT5g8+is7ML0zmO2bR5O23t7TZL2tlpPud7dZrN5zz/x2hoaGLlGx/S2tZGS0ubQ9uxrDyefOZV3N3dyMouoLPT8f0zMvNY9fZH6D10jE05399g4DBghVhcZmFPeheAo0uKaBWkLFA54tkbHW0/Y+Gd9dVkFbbwyF3BTEwx/KTrqV1U4CIPuStOVvPp51tsIhyXmshjD9/LxPEpZGTm8ewLq9i+cy+5+cV8tuFr4mIiCAsNdni/043NAOjc3UgcHcvI8GAysws5eiwHgOzcIvbuT2fKpPFcNSGV6po6MjLzyC8oASBkRBCJo2PRajWkJI0iOSHO4f3b2jtoa+8AwMfbk4AAX3Tu7gy5iFHW1rZ2Wtva0ajVpKUmEh0VTkZmHpnZ+QC2vmo0aq4Ym0RUZBhHj+WSlVMAQMaxXA4dyVKEeLnSYZQorRKpabAP0PREPK2vrZuAiGRN3vcUbSNJFB5vZ8+Rpp8sRHtKjpdz5Gg2ACPDQ1h0y01MHJ8CyC7XbQtv5ETpSU6UVlBeUUVufnEfIQJ4exm4+/b5/P7eRWi1GnZ/f5Cn/rmSo8dyMZvNtLS2YTR1csW4ZOLjolj5xge2D/eouCj++MjvfjRqmpo8ikeW3cM1V19h21dVXXfB93w+PHTu3LHo1/z+3kUY9Dq279zD08+/TmZ2QW/7b29m6ZLb0Ot1fLllJ08//zpFxSdobWunpbX1R64wMBiQUdOqepGc4xZZWpIkl6jZJ+Ctm2N6QuzNHyKSlujBzTP8f9b1a+tOcaK0AoAAfx/CQh3F4OVlsAVb2jvOOIz/7Jk5/RqbCAFGjAgiNjrC1t5lPrfL+VOJigzjrjsWOojwYnPt5AncunAOBr0OgLDQYKIiwmzts341mbtuvxm9tT08LJioiFBbe2trex+3diAyIC1idb1IXkm3XCoq4CCwHosnJ+AlECSrlZSs1lHEU+9EUpyOsGDXC752e3sHtfWnMFqDM3v2HeFXcxaf93iz2dwnkNODWq12SMhr1C4XNUE/NNCfULto56VAo1ajsb8njRqtRik6GJAWsasbegyFdJYrKkmOG2KvVeyxmgadE4G+6kvSV3c3NwwGpfxtsDMgLWJXl4SxU7Il73usoL1llM76iS16KtHU0kl1vfGi9CU2ZiS3zr+BuNjIc7Z7exkIscunKQxOBqQQ5bFhzyu7kjTJfiqTvPXUiNoLs6mlm4zcFk5UdBAW7HZB13Z3dyPAz5chWi1Gkwl3NzdioyOYkDbm4t/oD2A2mzF1/rzxo0bj6BJ3nvVeDaebqKk99R/3UaGXAemaGjxUDPUT6J1FYbWI57CGEpItndFb1G0hK7+Jb77/edFDT0+9LRiTl1/C19/sprG5pc9xjY3NVNf0zRNeDE6fbqam5ueJRX3WWDQrq4ADBzMAOaL64op3eO/D9RelnwoyA9IiGtwFhvoK5Bb3RkJ7y9qksyyjHD2VN5GeNEZTSydFpW00tZht5Wo/laSEWKZNmcjrb62lvaODtZ9sovh4GZOuGoenQU9jYzNHj+VyJD2LiRNSefKvD/Upd7tQdO5uBPj5oNVqMJk6OZKRzbJH/4aPjxdBwwJYctctjB+X/JPey0PnzvCgoRj0HjS3tFJVU8cTT69g1dsf0d5xhto6xRpebAakEP28BOt8QwnBmsgX7MeDDrMopN7xo1WYrkNUzJkayIN3RlywCAEC/H2ZO2c6x0sr2LZjD+3tHezavZ9du/df7Ft1ID4uivFpY9j57T4Aqmvrqa6tx8XF5YLTHKljRnHN1Wls2PQNAG1t7bS1tQM9Qg2kvcNIeUXlxb2JQcqAFKKvl4q00c5s2wvHT1r6jAvlfGLvBOCeIA2IeHo4s3D2MO5bFI7axYkd+1ooKjNyRaI70WGuaLWO3ry5S6S6toMDGbWIosj0SSPwMmhJHB3LE48/SEz0SL7astOWV+whMMCXCWljuHH2NJs11Khd0HvoGKLV4Oo6xKGwG+R0hq+PF54GD7q6Lfj5eTu4kPFxkSz+zVyam1s4eizX+p5qYqLCiYkeCchVNIEBvjQ2tuDn44Wn/tyrBkRHhrN0ySJcnF34Zsf3NLe0olGrGZeawJI7F6LXe7Ditfepra1Hr9eh1aptfQwaFkiAvw8dZ0z4+fo4pCfUGjV6Dx1ajQa12gU/X2802t5/dh46d/z9fHrb/RzbByoDtuj7VKOFtz5rY9XHTXZzB61F3mJvwbdc/C2PC6PDhvDA4lCuvzaQplYLH29p5rWPTtHUZESSuvD1EhgdpcXfyxmVSqSqto2cggaq61qRxC7chsDcGWEsuyuJoQHutr6YzV00NDTS2NyCWu1iFdP/b8qirb2D5uZWh5kXP5eG003U1p3CQ+cmC0uZbHzRGbBCBMjI7+T51Y18n95+1myLHvF1y/vFbpLjdTx6TzhXpnpTWtnNm5+28Pk3LXIRtNSFJHYh9fwUzQ77sGtzcRKZMSWYx36fStgIwy/9CBQuEwaka9pD/Eg1N0xxI6e4g6ZmsW+QRhJxcYZpV/rz6D1hhAe7klPczYtr2ti+34gkCiCoQHJCDuao5E1wAkQElQiiiCRYUyGCSJfFwhdbj3PqdDt/+q80UhICf9mHoHBZMKAtIkBzq4UPNzXx8po6zpjMNouIZMGgE1gwy5/f/yYYNzcX9h/r4pUPjRzNMyOJXSCZe63gWZbPtknnto6IXSTEevPIfWOZdnVYn37l5Bezdt1GQoKHcc+dC/u0b9+5l7fe/Zjw8BHcMv964qw1pukZOXzw0ReUlp0E5IKAWTMmM33aJNvMifSMHNas/YKs3AKMZ4xER4Uzf95MJl2ZhlarYeu273h3zWe2AE5UZBgLfj2bpIRY2/VLy07y8frNHDiYwZzZU1k4/3o2bPyGdZ9+2aevCaNjWHjzbHTubnyyfgtfbtmB0WgiKCiQ62dey+wZUzDodRw8nMnajzfa5iX6+nhx3dSrGJuSwLYdezhwKINfz53BtClXcupUI5+s30xlTR0L5s0iYVT0f/hJ6N8MyDyiPQYPJ2ZM0jF7sg7BLlgTGqRh+ZJQHr4zFLXamc+3dfLHl85wNN8iL2Qq9Fg+JxwtoRMITgiCCkGlQhCcQJB/CjhZz5O3zLx6/rnyANt2n+jTr6bGJo4ey+H4WUEcgPKKKrZ88y07vt3Hl5t3sG9fuq2tpraevQfSOdXQiL+/DyUnyvmfJ1/iw3VfALDvwFGeeOpldn23j6iIUMaNTSI3v5jljz/D2o83AVBWXsmhI5lYLCJDXIew5d/f8qe//tMhqpuZU8D6L7ay90A6ew+kU1ZWKdftCnDqdBPpx3Ioq6hEEuQATWFhKcsff5YVr7+Pt5eB1JTR1NTW89cnX+TNd9ZhMnVSVS3Pwm9sbsHPz4f8ouMsf/wZNn61Db3Bg4ysPDZ/vYu6ugZ27znI6jWfIVosg6LyaMALESA0SMPtN/owdYIHSCKjIt34y9IwbpsTiMks8OFXnTz7jpGaU6L1jB6B9W69gpO3nn2yAJ2Rharq3Sc4I6EiI7eOZ1fuY9vu4z+5v+UVVVRUVBMbHYFWq6Gg6HifCbtXXzmOVa/8nXvvvhUnZyeamluprqnnyy07aGhs4i9/fIDXXvobLz77OH9+bClqtZq9B9JtllSnc+PGG6bx0bsvsuz+OyirqCYjMw+Q5xHm5RXjoXMnbWwSpWUnKS0/yYJ5s9j48SoeefBu/P18mTN7Ghs/XsWfHr2PltZW8gqKWXzbPN5c+Q9efu6v/OvpP5GcEMfu7w5w8PAxW9+nTp7IGyv+zrKld+DpqedkZQ0xkeFcNWEs+YUlfL/vMDl5Rbi7uTJxfKptZsZAZlAIESA+0pVli4fyxIMhPPffI5k60YvSKpHn3jXy4hojza09talyobiEAKgQ7EQpnGUdJXvxqZzsjlOBICAIzgiCE8dy6vjLs7v4ZGPuj/bTbDaTlVtAdW0d1029kjFJ8RSVlHE0I8fhuJraenbt3s+hw5kY9B7ERo+kpraeE2UnCRkRRGx0uO3YyIhQkhPj5NK0s5Lx1TV1FBadwMXF2RZdra6po7SiktGjopk7ZzpGk5mDhzPPm4usqq4jO7cQL6slNFhTItFR4SSMjubU6SaHZTBAXg2gvuE0oigyPCiQuNgIxl8xho4OI6+89j7bdu4hbWwiV01I/dFnNhAYNEIEiI90Y/G8AOIi3Mgp6eapNzpYu9mEybbQt7zGfs+Xz9jcU8Gpr4XkbHfUyc5V7XVpBasrW1zaxOPP7OCZV/dgNHWft49lFdXk5hcTMTKUm264jqSEWOrrG8jLL3Y47quvd3Lzbffzyedb0Ot0DNForMteyCmSc00tMtsteVFdU8/yx58hYdxMNm3ezq03X89N118HQFZ2AcUlZUSODCUuJoKhgX5UVtWct6Km0ywvsaFRq9Fo+k5x6ux0rFV9eeW7BEWM55WV7zFvzq+4+aaZAKSlJjIuNZG8gmKcnZwHjTWEQSbEHqrqRD7Z2sn2A10OXy5j/z0zEoLVBbW6ome5njhssuWUxefUayFVVpFaz21qNvH2h0dZtebc69iAvFZNXl4JNbX1bNq8g73706mpre/jnt69eAEFx7bz1P/+gdPNzaxZ9wVV1XVotRrM5i6HD77ZOoHYfn6jt7cnc+dMZ/7cmbgO0WKRRLRaDW1t7ZQcL6e5qYXs3EK2bv8Ok6mTzOwCDhzK+MHn2mk2O6w909raTnNLW585h9dOnsgdv/01KpWK8pPVtr4GDQtgTHI8/n4+g8oawgBPX5yPYf4qlt/pysyrNGzYYWbbfrPDuqeCIFhtoyw8CYssPnpSFRZZfJIKSVAhSE62FIZc12oVHz1jSRG1i8CYUb4sWTSGKRNDOZx+tE+/2to7yMjKo+REGXoPHes+/RKzWV53JyeviH37HQXs7WVgTGI8u3bvp729AyeVE4EBfmTnFpJXcJyYKLmaprqmntKySuJiIwgNGU5WdgEatQtjUxJISR5Fa1sH3+85RFpqIt7enhQUHae1vd0mvLa2DoxGE4XFped0T3uWU9yxay9l5b0lb6WlJyksOkFY6HCiIsJsganY6JE8cN/tuLm6smHjv9m95xCLbrkRAI1Gg1arwcPDfdBYQxikQgT567fHjXZm3GhnltysYf02M1/vMVNaKTocJyEg4Gxd18ZiC9SAiKQSEXryiIgIggVJsFpGSQRBJNB3CJPSArjhujDGpwxFq3V85N/vPcz9D/8vAAEBvlRW1XDVxLH8eflSYmMiMJvNrFq9jjdXr+NE6Ulb2Vv6sRyefGYFWdkFpB/LZd6c6VxzdRpGo5Gd3+7jXy+/TfrRbM4YTezbn467zpXZM6YQ6O+4PmlUZBhpYxP518tvs/9gBsHBQ8nJK+L+e3/LsvvvAOBwehbPvvAG+QUlFBT2DTpp1GqSRscwbGgAL776DoeOZBISMpxDh46RV1DC7+6+lajIMIcIsYeHO3ExEWzavJ29+9O5euJYh3VOBxuDVoj2hA5z4g+3D+F387UUllnYcbCLrTZRquTlNHpcTJzAmshHEpEEC6hUCKITks36QXykJzdOC2LyhEDCRvQtMfPy9CRyZCh79h9h7/4jqNUuBA0LQK2WVzSLjZHzhmq1mujIMIYHBVJb38DI8BFEjgwhr6CEr77eRdCwAJYvW8LsmZPx9/Nh3o0z8DToefu9T1jz0QZcnJ0Zl5rIPXcssK1N4+PtSUREKAaDHo1azcQrUsjNK6amrp4Oo5HoyHCHnOLQQH9SkkeRnVNAbf0pfLw9iYwIsQVlAKZcMwGdzp3Vaz5l774j7PruIMmJsTzz5HKunTxRtnI6NyLCRxBgXTh4XGois341mYqT1dTVNzAieBh+Pl5EhIeg9xg81hAGQUL/59JhlCitFMks7OZofje5xSbKq00YjXKSvzeJ342b1kJokDOJMW6kjNKRFGu44AnFCoMbRYgXgLlborVd5HSThY4zFjzcVdbNCa1mUMa9FC4SihAVFPoByr9xBYV+gCJEBYV+gCJEBYV+gCJEBYV+gCJEBYV+gCJEBYV+gCJEBYV+gCJEBYV+gCJEBYV+gCJEBYV+gCJEBYV+gCJEBYV+wP8BCQcAzh+X9UMAAAAASUVORK5CYII="

DESIGN_CSS = """
:root{
--blue-700:#2555b8; --blue-600:#2f6fe4; --blue-500:#4a84ee;
--blue-50:#eaf2ff; --blue-25:#f4f8ff;
--ink-900:#1c2430; --ink-700:#3a4453; --ink-500:#6b7686; --ink-300:#a4adba;
--line:#e4e8ee; --bg:#f3f5f9; --white:#ffffff;
--green:#1f9d6f; --green-bg:#e7f7f0;
--amber:#d98b1c; --amber-bg:#fdf1de;
--red:#d5474f; --red-bg:#fbe9ea;
--purple:#7c5cd4; --purple-bg:#f1ecfb;
--radius:10px;
--shadow:0 1px 2px rgba(28,36,48,.06), 0 1px 1px rgba(28,36,48,.04);
}
*{box-sizing:border-box;}
button{font-family:inherit;}
/* SIDEBAR */
.sidebar{width:230px;flex:0 0 230px;background:var(--white);border-right:1px solid var(--line);display:flex;flex-direction:column;padding:20px 14px;}
.brand{display:flex;flex-direction:column;align-items:flex-start;gap:8px;padding:4px 6px 22px;}
.brand-logo{width:100%;max-width:148px;height:auto;display:block;margin:2px auto 0;}
.role-badge{display:inline-block;font-size:10px;font-weight:700;letter-spacing:.03em;color:var(--blue-700);background:var(--blue-50);padding:2px 7px;border-radius:100px;margin-top:8px;}
.nav-group{margin-bottom:16px;}
.nav-label{font-size:10.5px;font-weight:700;letter-spacing:.04em;color:var(--ink-300);padding:0 10px 6px;}
.nav-item{display:flex;align-items:center;gap:10px;padding:9px 10px;border-radius:8px;cursor:pointer;color:var(--ink-700);font-size:14px;font-weight:500;margin-bottom:2px;user-select:none;position:relative;}
.nav-item:hover{background:var(--blue-25);}
.nav-item.active{background:var(--blue-600);color:#fff;}
.nav-icon{width:17px;height:17px;flex:0 0 17px;display:flex;align-items:center;justify-content:center;}
.nav-icon svg{width:17px;height:17px;}
.nav-badge{margin-left:auto;background:var(--red);color:#fff;font-size:10.5px;font-weight:700;padding:1px 7px;border-radius:100px;}
.nav-item.active .nav-badge{background:rgba(255,255,255,.25);}
/* MAIN */
.topbar{height:60px;flex:0 0 60px;background:var(--white);border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 24px;}
.search{display:flex;align-items:center;gap:8px;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px 12px;width:300px;color:var(--ink-500);font-size:13.5px;}
.user{display:flex;align-items:center;gap:10px;cursor:pointer;padding:6px 8px;border-radius:8px;}
.user:hover{background:var(--bg);}
.user-dropdown-wrap{position:relative;}
.user-menu{
position:absolute;top:calc(100% + 8px);right:0;min-width:180px;
background:var(--white);border:1px solid var(--line);border-radius:10px;
box-shadow:0 8px 24px rgba(0,0,0,.12);padding:6px;display:none;z-index:50;
}
.user-menu.show{display:block;}
.user-menu-item{display:flex;align-items:center;gap:10px;padding:9px 10px;border-radius:7px;font-size:13px;font-weight:600;color:var(--ink-700);cursor:pointer;}
.user-menu-item:hover{background:var(--bg);}
.user-menu-item.danger{color:var(--red);}
.user-menu-item.danger:hover{background:var(--red-bg);}
.avatar{width:30px;height:30px;border-radius:50%;background:var(--blue-50);display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:var(--blue-700);}
.crumbs{font-size:12.5px;color:var(--ink-500);margin-bottom:14px;}
.crumbs b{color:var(--ink-900);font-weight:600;}
.page-title{font-size:22px;font-weight:700;margin:0 0 4px;}
.page-sub{font-size:13.5px;color:var(--ink-500);margin:0 0 22px;}
.card{background:var(--white);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);}
.pill{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;padding:4px 10px;border-radius:100px;white-space:nowrap;}
.pill.green{background:var(--green-bg);color:var(--green);}
.pill.amber{background:var(--amber-bg);color:var(--amber);}
.pill.red{background:var(--red-bg);color:var(--red);}
.pill.blue{background:var(--blue-50);color:var(--blue-700);}
.pill.purple{background:var(--purple-bg);color:var(--purple);}
.pill.grey{background:#eef0f3;color:var(--ink-500);}
.dot{width:8px;height:8px;border-radius:50%;flex:0 0 8px;}
.dot.green{background:var(--green);} .dot.amber{background:var(--amber);} .dot.red{background:var(--red);}
.btn{border:none;border-radius:8px;font-weight:600;font-size:13.5px;cursor:pointer;padding:10px 16px;display:inline-flex;align-items:center;gap:7px;transition:background .12s;}
.btn-primary{background:var(--blue-600);color:#fff;} .btn-primary:hover{background:var(--blue-700);}
.btn-primary:disabled{background:#c6d4ef;cursor:not-allowed;}
.btn-success{background:var(--green);color:#fff;} .btn-success:hover{background:#188059;}
.btn-ghost{background:var(--white);color:var(--ink-700);border:1px solid var(--line);} .btn-ghost:hover{background:var(--bg);}
.btn-danger-ghost{background:var(--white);color:var(--red);border:1px solid var(--line);} .btn-danger-ghost:hover{background:var(--red-bg);}
.btn-sm{padding:7px 12px;font-size:12.5px;}
label.field-label{display:block;font-size:13px;font-weight:600;color:var(--ink-700);margin-bottom:6px;}
select.input, input.input, textarea.input{width:100%;border:1px solid var(--line);border-radius:8px;padding:10px 12px;font-size:13.5px;color:var(--ink-900);background:var(--white);font-family:inherit;}
select.input:focus, input.input:focus, textarea.input:focus{outline:2px solid var(--blue-500);outline-offset:0;border-color:var(--blue-500);}
textarea.input{resize:vertical;min-height:70px;}
::-webkit-scrollbar{width:9px;height:9px;} ::-webkit-scrollbar-thumb{background:#d3d9e2;border-radius:6px;}
/* ---------- DASHBOARD ---------- */
.stat-row{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:22px;}
.stat-card{padding:20px 22px;border-radius:14px;}
.stat-top{display:flex;align-items:center;gap:8px;margin-bottom:14px;}
.stat-icon{width:19px;height:19px;flex:0 0 19px;display:flex;align-items:center;justify-content:center;}
.stat-label{font-size:13px;color:var(--ink-500);font-weight:600;}
.stat-value{font-size:30px;font-weight:700;line-height:1;}
.stat-sub{font-size:11.5px;color:var(--ink-300);margin-top:6px;}
.dash-grid{display:grid;grid-template-columns:1.3fr 1fr;gap:18px;align-items:start;margin-bottom:18px;}
.section-card{padding:20px 22px;}
.section-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;}
.section-head h3{font-size:14.5px;margin:0;}
.link-btn{font-size:12.5px;color:var(--blue-600);font-weight:600;cursor:pointer;}
.activity-item{display:flex;justify-content:space-between;align-items:center;gap:14px;padding:12px 0;border-bottom:1px solid var(--line);}
.activity-item:last-child{border-bottom:none;}
.act-left{display:flex;gap:12px;align-items:flex-start;}
.act-dot-wrap{padding-top:4px;}
.act-unit{font-size:13.5px;font-weight:600;}
.act-meta{font-size:12px;color:var(--ink-500);margin-top:2px;}
.room-health-row{display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid var(--line);}
.room-health-row:last-child{border-bottom:none;}
.room-health-name{font-size:13px;font-weight:600;width:110px;flex:0 0 110px;}
.health-bar{flex:1;height:9px;background:var(--bg);border-radius:100px;overflow:hidden;display:flex;}
.health-seg.good{background:var(--green);} .health-seg.issue{background:var(--amber);} .health-seg.replace{background:var(--red);}
.room-health-count{font-size:12px;color:var(--ink-500);width:60px;flex:0 0 60px;text-align:right;}
.issuetype-row{display:flex;align-items:center;gap:12px;padding:9px 0;}
.issuetype-name{width:150px;flex:0 0 150px;font-size:12.5px;color:var(--ink-700);}
.issuetype-bar-wrap{flex:1;height:8px;background:var(--bg);border-radius:100px;overflow:hidden;}
.issuetype-bar{height:100%;background:var(--blue-500);border-radius:100px;}
.issuetype-count{width:26px;flex:0 0 26px;text-align:right;font-size:12.5px;font-weight:600;color:var(--ink-700);}
/* Recent Activity (reference style) */
.ra-legend{display:flex;gap:14px;font-size:11.5px;color:var(--ink-500);}
.ra-legend span{display:flex;align-items:center;gap:5px;}
.ra-legend .dot{display:inline-block;}
.activity-card{display:flex;justify-content:space-between;align-items:center;gap:16px;background:var(--bg);border-left:4px solid var(--line);border-radius:8px;padding:14px 16px;margin-bottom:10px;}
.activity-card:last-child{margin-bottom:0;}
.activity-card.st-resolved{border-left-color:var(--green);}
.activity-card.st-progress{border-left-color:var(--amber);}
.activity-card.st-followup{border-left-color:var(--red);}
.ac-title{font-size:14px;font-weight:700;color:var(--ink-900);}
.ac-sub{font-size:12px;color:var(--ink-500);margin-top:3px;}
.ac-tag{display:inline-block;background:var(--white);border:1px solid var(--line);border-radius:6px;padding:3px 9px;font-size:11px;color:var(--ink-700);margin-top:7px;}
.ac-right{text-align:right;flex:0 0 auto;}
.ac-date-label{font-size:10.5px;color:var(--ink-300);text-transform:uppercase;letter-spacing:.03em;}
.ac-date-value{font-size:12.5px;color:var(--ink-700);margin-top:2px;}
/* Room at a Glance (reference style) */
.glance-wrap{display:flex;align-items:center;gap:28px;}
.glance-icon{flex:0 0 100px;text-align:center;}
.glance-icon-box{width:80px;height:80px;border-radius:14px;background:linear-gradient(155deg,#5fb3e8,#2f8fd6);display:flex;align-items:center;justify-content:center;margin:0 auto 10px;}
.glance-room-name{font-size:12.5px;font-weight:700;color:var(--ink-900);line-height:1.3;}
.glance-chart{flex:1;}
.glance-bar-row{display:flex;align-items:center;gap:10px;margin-bottom:10px;}
.glance-bar-row:last-child{margin-bottom:0;}
.glance-bar-track{flex:1;height:20px;background:var(--bg);border-radius:5px;overflow:hidden;}
.glance-bar-fill{height:100%;border-radius:5px;}
.glance-axis{display:flex;justify-content:space-between;font-size:10.5px;color:var(--ink-300);margin-top:6px;padding-left:0;}
.glance-stats{flex:0 0 190px;border-left:1px solid var(--line);padding-left:22px;}
.glance-total-label{font-size:11px;color:var(--ink-500);}
.glance-total-value{font-size:26px;font-weight:700;color:var(--ink-900);margin:2px 0 14px;}
.glance-legend-row{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--ink-700);margin-bottom:10px;}
.glance-legend-row:last-child{margin-bottom:0;}
.glance-legend-count{margin-left:auto;font-weight:700;color:var(--ink-900);}
/* ---------- REPORTS ---------- */
.reports-toolbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;gap:16px;flex-wrap:wrap;}
.toolbar-left{display:flex;align-items:center;gap:10px;flex-wrap:wrap;}
.search-input{position:relative;width:230px;}
.search-input input{padding-left:34px;}
.search-input svg{position:absolute;left:11px;top:50%;transform:translateY(-50%);color:var(--ink-300);}
.filter-select{width:auto;padding:9px 10px;font-size:13px;}
.status-toggle{display:flex;background:var(--bg);border-radius:8px;padding:3px;gap:2px;}
.status-toggle-btn{padding:7px 13px;border-radius:6px;font-size:12.5px;font-weight:600;color:var(--ink-500);cursor:pointer;}
.status-toggle-btn.active{background:var(--white);color:var(--ink-900);box-shadow:var(--shadow);}
.sortby{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--ink-500);}
.count-badge{font-size:13px;color:var(--ink-500);} .count-badge b{color:var(--ink-900);}
table.reports-table{width:100%;border-collapse:collapse;font-size:13.5px;}
table.reports-table thead th{text-align:left;font-size:11.5px;letter-spacing:.03em;color:var(--ink-500);padding:12px 16px;border-bottom:1px solid var(--line);font-weight:700;}
table.reports-table tbody td{padding:14px 16px;border-bottom:1px solid var(--line);vertical-align:top;color:var(--ink-700);}
table.reports-table tbody tr:last-child td{border-bottom:none;}
table.reports-table tbody tr{cursor:pointer;}
table.reports-table tbody tr:hover{background:var(--blue-25);}
.rep-id{font-family:ui-monospace,monospace;font-size:12.5px;color:var(--ink-500);}
.rep-unit{font-weight:600;color:var(--ink-900);}
.rep-teacher{font-size:12px;color:var(--ink-500);margin-top:2px;}
.issue-tags{display:flex;flex-wrap:wrap;gap:5px;max-width:220px;}
.issue-tag{background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:2px 8px;font-size:11.5px;color:var(--ink-700);}
.empty-state{padding:60px 20px;text-align:center;color:var(--ink-500);}
/* report drawer */
.drawer-overlay{position:fixed;inset:0;background:rgba(20,26,36,.4);display:none;align-items:stretch;justify-content:flex-end;z-index:60;}
.drawer-overlay.show{display:flex;}
.drawer{width:min(420px, 100vw);background:var(--white);height:100%;overflow-y:auto;padding:26px;box-shadow:-8px 0 24px rgba(0,0,0,.12);}
.drawer-close{position:absolute;top:22px;right:22px;cursor:pointer;color:var(--ink-500);}
.drawer h2{font-size:17px;margin:0 0 2px;}
.drawer-sub{font-size:12.5px;color:var(--ink-500);margin-bottom:18px;}
.drawer-row{padding:12px 0;border-bottom:1px solid var(--line);}
.drawer-row:last-child{border-bottom:none;}
.dr-header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-right:20px;}
.dr-meta-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:14px 0;border-bottom:1px solid var(--line);margin-bottom:2px;}
.drawer-label{font-size:11.5px;font-weight:700;letter-spacing:.03em;color:var(--ink-300);margin-bottom:6px;}
.drawer-value{font-size:13.5px;color:var(--ink-900);}
.drawer-comment-box{background:var(--bg);border-radius:8px;padding:12px 14px;font-size:13px;color:var(--ink-700);font-style:italic;}
.drawer-actions{margin-top:16px;display:flex;gap:10px;}
.drawer-actions .btn{flex:1;justify-content:center;}
.ai-box{background:var(--blue-25);border:1px solid var(--blue-50);border-radius:10px;padding:14px 16px;margin-top:18px;}
.ai-box-head{display:flex;align-items:center;gap:8px;font-size:13px;font-weight:700;color:var(--blue-700);}
.ai-box-sub{font-size:11.5px;color:var(--ink-500);margin:6px 0 10px;}
.ai-suggestion-wrap{display:flex;flex-wrap:wrap;gap:7px;}
.ai-suggestion-chip{background:var(--white);border:1px solid var(--line);border-radius:100px;padding:7px 13px;font-size:12.5px;color:var(--ink-700);cursor:pointer;transition:border-color .12s, background .12s;white-space:nowrap;}
.ai-suggestion-chip:hover{border-color:var(--blue-500);}
.ai-suggestion-chip.picked{background:var(--blue-50);border-color:var(--blue-500);color:var(--blue-700);font-weight:600;}
/* ---------- UNIT INVENTORY (shared with teacher app) ---------- */
.room-tabs{display:flex;gap:6px;margin-bottom:16px;border-bottom:1px solid var(--line);}
.room-tab{padding:11px 18px;font-size:13.5px;font-weight:600;color:var(--ink-500);cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px;}
.room-tab.active{color:var(--ink-900);border-bottom-color:var(--blue-600);}
.inv-toolbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;}
.inv-filters{display:flex;gap:14px;font-size:13px;color:var(--ink-700);align-items:center;}
.inv-filters label{display:flex;align-items:center;gap:6px;cursor:pointer;}
.unit-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:14px;}
.unit-card{background:var(--white);border:1px solid var(--line);border-radius:var(--radius);padding:16px 10px 12px;text-align:center;cursor:pointer;position:relative;transition:border-color .12s, box-shadow .12s;}
.unit-card:hover{border-color:var(--blue-500);box-shadow:var(--shadow);}
.unit-card .status-dot{position:absolute;top:10px;right:10px;}
.unit-card svg{margin-bottom:8px;}
.unit-card-name{font-size:13px;font-weight:600;color:var(--ink-900);}
.back-link{display:inline-flex;align-items:center;gap:6px;color:var(--blue-600);font-size:13px;font-weight:600;cursor:pointer;margin-bottom:14px;}
.unit-title-row{display:flex;align-items:center;gap:12px;}
.unit-title-row h1{font-size:21px;margin:0;}
.detail-grid{display:grid;grid-template-columns:1fr 300px;gap:20px;align-items:start;}
.tabs-row{display:flex;gap:4px;background:var(--bg);border-radius:9px;padding:4px;margin-bottom:18px;width:fit-content;}
.tab-btn{padding:8px 16px;border-radius:7px;font-size:13px;font-weight:600;color:var(--ink-500);cursor:pointer;}
.tab-btn.active{background:var(--white);color:var(--ink-900);box-shadow:var(--shadow);}
.tab-panel{display:none;} .tab-panel.active{display:block;}
.spec-table{width:100%;border-collapse:collapse;}
.spec-table tr td{padding:11px 4px;border-bottom:1px solid var(--line);font-size:13.5px;}
.spec-table tr:last-child td{border-bottom:none;}
.spec-key{color:var(--ink-500);width:42%;} .spec-val{color:var(--ink-900);font-weight:600;text-align:right;}
.sw-list{list-style:none;margin:0;padding:0;}
.sw-list li{display:flex;justify-content:space-between;padding:10px 2px;border-bottom:1px solid var(--line);font-size:13.5px;}
.sw-list li:last-child{border-bottom:none;}
.sw-name{color:var(--ink-900);font-weight:500;} .sw-meta{color:var(--ink-300);font-size:12px;}
.history-item{display:flex;gap:14px;padding:16px 0;border-bottom:1px solid var(--line);}
.history-item:last-child{border-bottom:none;}
.history-rail{display:flex;flex-direction:column;align-items:center;flex:0 0 12px;padding-top:4px;}
.history-dot{width:9px;height:9px;border-radius:50%;}
.history-body{flex:1;}
.history-top{display:flex;justify-content:space-between;gap:10px;margin-bottom:4px;}
.history-issue{font-size:13.5px;font-weight:600;color:var(--ink-900);}
.history-date{font-size:12px;color:var(--ink-300);white-space:nowrap;}
.history-comment{font-size:13px;color:var(--ink-500);margin:4px 0;font-style:italic;}
.history-action{font-size:13px;color:var(--ink-700);background:var(--bg);border-radius:7px;padding:8px 10px;margin-top:6px;}
.history-action b{color:var(--ink-900);}
.side-card{padding:18px;margin-bottom:16px;}
.side-card h4{margin:0 0 12px;font-size:13px;text-transform:uppercase;letter-spacing:.03em;color:var(--ink-500);}
.issue-count-big{font-size:30px;font-weight:700;color:var(--ink-900);}
.issue-count-label{font-size:12.5px;color:var(--ink-500);}
/* ---------- ERROR ANALYTICS ---------- */
.analytics-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:18px;}
.rank-row{display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid var(--line);}
.rank-row:last-child{border-bottom:none;}
.rank-num{width:22px;height:22px;border-radius:6px;background:var(--bg);display:flex;align-items:center;justify-content:center;font-size:11.5px;font-weight:700;color:var(--ink-500);flex:0 0 22px;}
.rank-row.top .rank-num{background:var(--red-bg);color:var(--red);}
.rank-main{flex:1;}
.rank-title{font-size:13.5px;font-weight:600;}
.rank-sub{font-size:12px;color:var(--ink-500);margin-top:2px;}
.rank-count{font-size:15px;font-weight:700;color:var(--ink-900);}
.rank-count-label{font-size:10.5px;color:var(--ink-300);text-align:right;}
/* ---------- ESCALATION ---------- */
.escalation-banner{display:flex;gap:14px;align-items:flex-start;background:var(--red-bg);border:1px solid #f3cdd0;border-radius:10px;padding:16px 18px;margin-bottom:20px;}
.escalation-banner svg{flex:0 0 20px;color:var(--red);margin-top:1px;}
.escalation-banner-text{font-size:13px;color:#8a3339;}
.esc-card{padding:20px 22px;margin-bottom:14px;}
.esc-top{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:14px;}
.esc-unit{font-size:16px;font-weight:700;}
.esc-room{font-size:12.5px;color:var(--ink-500);margin-top:2px;}
.esc-count-box{text-align:center;background:var(--red-bg);border-radius:8px;padding:8px 16px;}
.esc-count-num{font-size:20px;font-weight:700;color:var(--red);}
.esc-count-label{font-size:10px;color:var(--red);font-weight:600;}
.esc-timeline{display:flex;gap:6px;margin-bottom:14px;flex-wrap:wrap;}
.esc-timeline-chip{font-size:11.5px;background:var(--bg);border-radius:6px;padding:4px 9px;color:var(--ink-700);}
.esc-footer{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;}
.esc-status-select{width:auto;padding:8px 10px;font-size:12.5px;}
/* ---------- SETTINGS (shared pattern) ---------- */
.settings-tabs{display:flex;gap:4px;background:var(--bg);border-radius:9px;padding:4px;width:fit-content;margin-bottom:20px;}
.settings-tab{padding:9px 18px;border-radius:7px;font-size:13.5px;font-weight:600;color:var(--ink-500);cursor:pointer;}
.settings-tab.active{background:var(--white);color:var(--ink-900);box-shadow:var(--shadow);}
.settings-panel{display:none;max-width:640px;} .settings-panel.active{display:block;}
.settings-layout{display:flex;gap:24px;align-items:flex-start;}
.settings-menu-col{flex:0 0 230px;}
.settings-menu{background:var(--white);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);padding:6px;}
.settings-menu-item{display:flex;align-items:center;gap:12px;padding:12px 10px;border-bottom:1px solid var(--line);cursor:pointer;border-radius:8px;}
.settings-menu-item:last-child{border-bottom:none;}
.settings-menu-item:hover{background:var(--bg);}
.settings-menu-item.active{background:var(--blue-25);}
.settings-menu-icon{width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex:0 0 32px;}
.settings-menu-icon.purple{background:#f1ecfb;color:#7c5cd4;}
.settings-menu-icon.orange{background:var(--amber-bg);color:var(--amber);}
.settings-menu-icon.blue{background:var(--blue-50);color:var(--blue-600);}
.settings-menu-label{font-size:13.5px;font-weight:600;color:var(--ink-700);}
.settings-menu-item.active .settings-menu-label{color:var(--ink-900);}
.settings-logout-btn{margin-top:12px;width:100%;padding:13px;border-radius:10px;border:none;background:linear-gradient(180deg,#6b7280,#374151);color:#fff;font-weight:700;font-size:13.5px;cursor:pointer;transition:background .12s;}
.settings-logout-btn:hover{background:linear-gradient(180deg,#4b5563,#1f2937);}
.settings-content{flex:1;min-width:0;}
.settings-card{padding:26px;margin-bottom:18px;}
.settings-card-title{font-size:15px;margin:0 0 18px;}
.form-row{margin-bottom:20px;} .form-row-2{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px;}
.form-footer{display:flex;justify-content:flex-end;gap:10px;margin-top:6px;}
.profile-row{display:flex;align-items:center;gap:16px;margin-bottom:22px;}
.avatar-lg{width:56px;height:56px;border-radius:50%;background:var(--blue-50);color:var(--blue-700);display:flex;align-items:center;justify-content:center;font-weight:700;font-size:17px;flex:0 0 56px;}
.profile-fixed-name{font-size:15px;font-weight:700;color:var(--ink-900);}
.profile-field-row{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:16px 0;border-bottom:1px solid var(--line);}
.profile-field-label{font-size:11.5px;font-weight:700;letter-spacing:.03em;color:var(--ink-300);text-transform:uppercase;margin-bottom:4px;}
.profile-field-value{font-size:13.5px;color:var(--ink-900);font-weight:500;}
.profile-inline-edit{padding:0 0 16px;margin-top:-8px;}
.toggle-row{display:flex;justify-content:space-between;align-items:center;gap:20px;padding:16px 0;border-bottom:1px solid var(--line);}
.toggle-row-title{font-size:13.5px;font-weight:600;color:var(--ink-900);}
.toggle-row-sub{font-size:12.5px;color:var(--ink-500);margin-top:3px;max-width:400px;}
.switch{position:relative;display:inline-block;width:40px;height:22px;flex:0 0 40px;}
.switch input{opacity:0;width:0;height:0;}
.switch .slider{position:absolute;inset:0;background:var(--line);border-radius:100px;cursor:pointer;transition:background .15s;}
.switch .slider::before{content:"";position:absolute;width:16px;height:16px;left:3px;top:3px;background:#fff;border-radius:50%;transition:transform .15s;box-shadow:0 1px 2px rgba(0,0,0,.2);}
.switch input:checked + .slider{background:var(--blue-600);}
.switch input:checked + .slider::before{transform:translateX(18px);}
.helptext{font-size:12px;color:var(--ink-300);margin-top:6px;}
.btn-danger{background:var(--red);color:#fff;} .btn-danger:hover{background:#b93a41;}
/* ---------- USER REQUESTS (messenger-style) ---------- */
.req-banner{display:flex;align-items:center;gap:14px;background:var(--blue-50);border:1px solid #cfe0fb;border-radius:12px;padding:14px 18px;margin-bottom:18px;}
.req-banner svg{flex:0 0 20px;color:var(--blue-600);}
.req-banner-text{flex:1;font-size:13.5px;color:var(--ink-700);}
.req-banner-text b{color:var(--ink-900);}
.req-shell{display:grid;grid-template-columns:350px 1fr;min-height:590px;overflow:hidden;}
.req-side{border-right:1px solid var(--line);display:flex;flex-direction:column;min-width:0;}
.req-side-head{padding:14px;border-bottom:1px solid var(--line);}
.req-side-head .status-toggle{width:100%;}
.req-side-head .status-toggle-btn{flex:1;text-align:center;padding:7px 4px;white-space:nowrap;}
.req-tab-count{display:inline-block;min-width:18px;margin-left:4px;padding:0 5px;border-radius:100px;background:var(--bg);color:var(--ink-500);font-size:11px;font-weight:700;line-height:18px;}
.status-toggle-btn.active .req-tab-count{background:var(--blue-50);color:var(--blue-700);}
.req-filters{display:flex;gap:8px;margin-top:10px;}
.req-filters .search-input{flex:1;width:auto;}
.req-list{flex:1;overflow-y:auto;max-height:640px;}
.req-item{display:flex;gap:12px;align-items:center;padding:13px 14px;cursor:pointer;border-bottom:1px solid var(--line);border-left:3px solid transparent;}
.req-item:hover{background:var(--blue-25);}
.req-item.selected{background:var(--blue-50);border-left-color:var(--blue-600);}
.req-avatar{width:40px;height:40px;flex:0 0 40px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13.5px;}
.req-avatar.teacher{background:var(--blue-50);color:var(--blue-700);}
.req-avatar.technician{background:var(--purple-bg);color:var(--purple);}
.req-item.selected .req-avatar{background:var(--white);}
.req-avatar.lg{width:56px;height:56px;flex:0 0 56px;font-size:17px;}
.req-item-main{flex:1;min-width:0;}
.req-item-name{font-size:13.5px;font-weight:600;color:var(--ink-900);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.req-item-sub{font-size:12px;color:var(--ink-500);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px;}
.req-item-time{flex:0 0 auto;font-size:11.5px;color:var(--ink-300);align-self:flex-start;padding-top:2px;}
.req-list-empty{padding:50px 20px;text-align:center;font-size:13px;color:var(--ink-500);}
.req-detail{display:flex;flex-direction:column;min-width:0;}
.req-detail-empty{margin:auto;text-align:center;color:var(--ink-500);padding:40px;font-size:13.5px;}
.req-detail-empty svg{color:var(--ink-300);margin-bottom:10px;}
.req-detail-head{display:flex;align-items:center;gap:16px;padding:22px 26px;border-bottom:1px solid var(--line);}
.req-detail-head h2{font-size:18px;margin:0 0 4px;}
.req-detail-sub{font-size:12.5px;color:var(--ink-500);}
.req-detail-body{padding:8px 26px 22px;flex:1;overflow-y:auto;}
.req-section-label{font-size:11.5px;font-weight:700;letter-spacing:.03em;color:var(--ink-300);margin:18px 0 2px;}
.req-info-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 28px;}
.req-info-cell{padding:12px 0;border-bottom:1px solid var(--line);min-width:0;}
.req-info-value{font-size:13.5px;color:var(--ink-900);font-weight:500;word-break:break-word;}
.req-detail-foot{border-top:1px solid var(--line);padding:14px 26px;display:flex;gap:10px;justify-content:flex-end;align-items:center;}
.req-foot-hint{flex:1;font-size:12.5px;color:var(--ink-500);}
.req-outcome{flex:1;font-size:13px;color:var(--ink-700);}
.req-outcome b{color:var(--ink-900);}
.modal-overlay{position:fixed;inset:0;background:rgba(20,26,36,.45);display:none;align-items:center;justify-content:center;z-index:70;padding:20px;}
.modal-overlay.show{display:flex;}
.modal{width:min(440px,100%);padding:24px;}
.modal h3{margin:0 0 6px;font-size:16px;}
.modal p{margin:0 0 16px;font-size:13px;color:var(--ink-500);line-height:1.5;}
@media (max-width:1000px){ .req-shell{grid-template-columns:1fr;} .req-side{border-right:none;border-bottom:1px solid var(--line);} .req-list{max-height:280px;} .req-info-grid{grid-template-columns:1fr;} }
/* toast */
.toast{position:fixed;bottom:26px;right:26px;background:var(--ink-900);color:#fff;padding:14px 18px;border-radius:10px;font-size:13.5px;font-weight:500;display:flex;align-items:center;gap:10px;box-shadow:0 8px 24px rgba(0,0,0,.18);transform:translateY(20px);opacity:0;pointer-events:none;transition:all .25s ease;z-index:80;}
.toast.show{transform:translateY(0);opacity:1;}
.toast .dot.green{background:#4ade80;}
"""

TEACHER_CSS = """
.role-badge{display:inline-block;font-size:10px;font-weight:700;letter-spacing:.03em;color:var(--blue-700);background:var(--blue-50);padding:2px 7px;border-radius:100px;}
.nav-item{ display:flex;align-items:center;gap:10px; padding:9px 10px;border-radius:8px;cursor:pointer; color:var(--ink-700);font-size:14px;font-weight:500; margin-bottom:2px;user-select:none; }
.pill{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;padding:4px 10px;border-radius:100px;}
textarea.input{resize:vertical;min-height:80px;}
.glance-axis{display:flex;justify-content:space-between;font-size:10.5px;color:var(--ink-300);margin-top:6px;}
.wizard-steps{display:flex;align-items:center;gap:0;margin-bottom:26px;}
.wz-step{display:flex;align-items:center;gap:9px;}
.wz-num{ width:26px;height:26px;border-radius:50%;background:var(--bg);border:1px solid var(--line); display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:var(--ink-500); flex:0 0 26px; }
.wz-step.done .wz-num{background:var(--green);border-color:var(--green);color:#fff;}
.wz-step.current .wz-num{background:var(--blue-600);border-color:var(--blue-600);color:#fff;}
.wz-step-label{font-size:13px;font-weight:600;color:var(--ink-500);}
.wz-step.current .wz-step-label, .wz-step.done .wz-step-label{color:var(--ink-900);}
.wz-line{width:56px;height:1px;background:var(--line);margin:0 10px;}
.form-card{max-width:640px;padding:26px;}
.chip-grid{display:flex;flex-wrap:wrap;gap:8px;}
.chip{ border:1px solid var(--line);border-radius:100px;padding:8px 14px;font-size:13px; color:var(--ink-700);cursor:pointer;user-select:none;background:var(--white);font-weight:500; }
.chip.selected{background:var(--blue-600);border-color:var(--blue-600);color:#fff;}
.chip.other{border-style:dashed;}
.other-issue-box{margin-top:12px;display:none;}
.other-issue-box.show{display:block;}
.form-footer{display:flex;justify-content:flex-end;gap:10px;margin-top:26px;padding-top:20px;border-top:1px solid var(--line);}
.review-card{max-width:640px;padding:26px;}
.review-row{display:flex;justify-content:space-between;padding:12px 0;border-bottom:1px solid var(--line);gap:20px;}
.review-row:last-child{border-bottom:none;}
.review-label{font-size:12.5px;color:var(--ink-500);font-weight:600;flex:0 0 150px;}
.review-value{font-size:13.5px;color:var(--ink-900);text-align:right;flex:1;}
.review-chips{display:flex;flex-wrap:wrap;gap:6px;justify-content:flex-end;}
.review-note{background:var(--blue-25);border:1px solid var(--blue-50);border-radius:8px;padding:12px 14px;font-size:12.5px;color:var(--blue-700);margin-top:18px;display:flex;gap:8px;align-items:flex-start;}
.confirm-wrap{max-width:520px;text-align:center;padding:44px 30px;}
.confirm-icon{ width:56px;height:56px;border-radius:50%;background:var(--green-bg);color:var(--green); display:flex;align-items:center;justify-content:center;margin:0 auto 18px; }
.confirm-id{font-family:ui-monospace,monospace;background:var(--bg);border-radius:6px;padding:3px 9px;font-size:13px;color:var(--ink-700);}
.toolbar-left{display:flex;align-items:center;gap:10px;}
.search-input{position:relative;width:250px;}
.sortby select{width:auto;padding:8px 10px;font-size:13px;}
.empty-state svg{margin-bottom:12px;color:var(--ink-300);}
.unit-detail-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:22px;}
.soon{padding:60px 30px;text-align:center;color:var(--ink-500);}
.profile-fixed-block{margin-bottom:16px;}
.profile-field-label{font-size:11.5px;font-weight:700;letter-spacing:.03em;color:var(--ink-300);text-transform:uppercase;margin-bottom:6px;}
.profile-fixed-name{font-size:14px;color:var(--ink-900);font-weight:600;}
.profile-fixed-name.muted{color:var(--ink-500);font-weight:500;}
.profile-divider{border:none;border-top:1px solid var(--line);margin:18px 0;}
.contact-info-row{display:flex;align-items:center;gap:10px;padding:8px 0;margin-bottom:6px;color:var(--ink-500);}
.contact-info-value{font-size:13.5px;color:var(--ink-900);font-weight:500;flex:1;}
.contact-info-edit{color:var(--ink-300);cursor:pointer;display:flex;align-items:center;}
.contact-info-edit:hover{color:var(--blue-600);}
.profile-inline-edit{padding:0 0 12px 25px;margin-top:-6px;}
.pw-wrap{position:relative;}
.pw-wrap input{padding-right:40px;}
.pw-eye{position:absolute;right:11px;top:50%;transform:translateY(-50%);cursor:pointer;color:var(--ink-300);display:flex;}
.pw-eye:hover{color:var(--ink-500);}
.pw-strength{margin:-10px 0 18px;}
.pw-strength-bar{height:5px;background:var(--line);border-radius:3px;overflow:hidden;margin-bottom:6px;}
.pw-strength-fill{height:100%;width:0%;background:var(--red);border-radius:3px;transition:width .2s,background .2s;}
"""
