"""Pemuatan model XGBoost hasil penelitian dan perhitungan peluang anomali beserta nilai SHAP.

Urutan dan pengodean fitur sama dengan `penelitian/src/persiapan.py`: enam parameter panel, jenis kelamin
(L = 1, P = 0), dan umur. Status ditentukan dengan aturan yang sama dengan evaluasi penelitian dan rancangan BAB III,
yaitu peluang anomali > ambang berarti perlu ditinjau.
"""
import os
from functools import lru_cache

import numpy as np
import pandas as pd
import shap
import xgboost as xgb

from ..models import FITUR


def berkas_model(folder, versi):
    return os.path.join(folder, versi + '.json')


@lru_cache(maxsize=4)
def _muat(path, waktu_ubah):
    m = xgb.XGBClassifier()
    m.load_model(path)
    penjelas = shap.TreeExplainer(m)
    # expected_value awal hanya taksiran dari base_score. Nilai dasar yang memenuhi sifat aditif
    # (phi_0 + jumlah phi_j = log-odds) baru terisi setelah shap_values dipanggil, dan nilainya sama
    # untuk masukan apa pun. Satu baris nol dipakai agar nilai dasar benar sejak model dimuat.
    penjelas.shap_values(pd.DataFrame([[0.0] * len(FITUR)], columns=FITUR))
    return m, penjelas


def muat(folder, versi):
    path = berkas_model(folder, versi)
    if not os.path.exists(path):
        raise FileNotFoundError('Berkas model %s tidak ditemukan. Jalankan perintah impor-model.' % path)
    return _muat(path, os.path.getmtime(path))


def matriks_fitur(profil):
    """profil: daftar dict dengan kunci FITUR (jenis_kelamin berupa 'L' atau 'P')."""
    x = pd.DataFrame([{k: p[k] for k in FITUR} for p in profil], columns=FITUR)
    x['jenis_kelamin'] = (x['jenis_kelamin'] == 'L').astype(int)
    return x.astype(float)


def prediksi(folder, versi, profil):
    """Kembalikan (peluang, nilai_shap, nilai_dasar). nilai_shap berukuran (n, 8) dalam satuan log-odds."""
    m, penjelas = muat(folder, versi)
    x = matriks_fitur(profil)
    peluang = m.predict_proba(x)[:, 1]
    nilai = np.asarray(penjelas.shap_values(x))
    return peluang, nilai, float(np.ravel(penjelas.expected_value)[0])


def nilai_dasar(folder, versi):
    """Nilai dasar SHAP (phi_0): rata-rata keluaran model dalam log-odds."""
    _, penjelas = muat(folder, versi)
    return float(np.ravel(penjelas.expected_value)[0])


def status_dari(peluang, ambang):
    return 'perlu_ditinjau' if peluang > ambang else 'tidak_ada_indikasi'
