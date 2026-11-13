# -*- coding: utf-8 -*-
"""Petunjuk pola untuk profil yang ditandai.

Model XGBoost hanya menghasilkan peluang anomali (biner) dan tidak menyebut jenis anomali. Petugas perlu
tahu apa yang harus diperiksa, sehingga layanan menurunkan petunjuk pola dari nilai SHAP profil itu:

  dorongan rendah = jumlah nilai SHAP positif dari parameter panel yang nilainya di bawah median profil
                    normal (6.872 profil hasil persiapan data, Tabel 4.1);
  bila dorongan rendah >= 50% dari seluruh nilai SHAP positif, pola menyerupai pengenceran (kadar panel
  turun bersamaan); bila tidak, pola menyerupai sampel tertukar (kombinasi nilai panel kurang lazim untuk
  jenis kelamin dan umur pasien).

Aturan yang sama diuji pada data uji S2 oleh penelitian/src/uji_petunjuk_pola.py.
"""

PANEL = ('kolesterol_total', 'hdl', 'ldl', 'trigliserida', 'urea', 'kreatinin')

# median profil normal hasil persiapan data (penelitian/hasil/uji_petunjuk_pola.json, Tabel 4.1)
MEDIAN_PROFIL_NORMAL = {'kolesterol_total': 206.0, 'hdl': 61.0, 'ldl': 112.0, 'trigliserida': 165.0,
                        'urea': 27.0, 'kreatinin': 0.8}
BATAS_DORONGAN_RENDAH = 0.5


def petunjuk_pola(kontribusi):
    """kontribusi: [{'nama_fitur', 'nilai_fitur', 'nilai_shap'}] satu profil.
    Mengembalikan pola ('pengenceran' atau 'tertukar'), proporsi dorongan rendah, dan parameter panel yang
    nilainya di bawah median profil normal serta mendorong ke arah anomali (urut dari SHAP terbesar)."""
    positif = sum(k['nilai_shap'] for k in kontribusi if k['nilai_shap'] > 0)
    rendah = [k for k in kontribusi
              if k['nama_fitur'] in PANEL and k['nilai_shap'] > 0
              and k['nilai_fitur'] < MEDIAN_PROFIL_NORMAL[k['nama_fitur']]]
    proporsi = sum(k['nilai_shap'] for k in rendah) / positif if positif > 0 else 0.0
    rendah.sort(key=lambda k: -k['nilai_shap'])
    return {'pola': 'pengenceran' if proporsi >= BATAS_DORONGAN_RENDAH else 'tertukar',
            'proporsi_dorongan_rendah': round(proporsi, 4),
            'parameter_rendah': [k['nama_fitur'] for k in rendah]}
