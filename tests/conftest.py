import csv
import os
from datetime import date

import numpy as np
import pytest
import xgboost as xgb
from werkzeug.security import generate_password_hash

from app import create_app
from app.ekstensi import db
from app.layanan.sumber_silakes import KOLOM
from app.models import FITUR, ModelDeteksi, Pengguna

KATA_SANDI = 'rahasia123'


def _tsv(path):
    """Delapan surat buatan untuk uji: lima memenuhi aturan persiapan, tiga dilewati."""
    rng = np.random.default_rng(0)
    baris = []
    for i in range(5):
        baris.append([1000 + i, 'a%015d' % i, '2026-11-0%d' % (i + 1), 'L' if i % 2 else 'P', 40 + i,
                      '%.0f' % rng.uniform(150, 250), '45', '120', '150', '30', '0,9'])
    baris.append([1005, 'b000000000000000', '2026-11-02', 'P', 0, '200', '45', '120', '150', '30', '0.9'])
    baris.append([1006, 'b000000000000001', '2026-11-02', 'L', 50, '200', '', '120', '150', '30', '0.9'])
    baris.append([1007, 'b000000000000002', '2026-11-03', 'L', 50, '200', '45', '120', '150', '30', 'O.7'])
    baris.append([900, 'c000000000000000', '2026-10-30', 'L', 50, '200', '45', '120', '150', '30', '0.9'])
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, delimiter='\t')
        w.writerow(KOLOM)
        w.writerows(baris)


def _model(folder):
    rng = np.random.default_rng(1)
    x = rng.normal(size=(200, len(FITUR)))
    y = (x[:, 0] + rng.normal(size=200) > 0).astype(int)
    m = xgb.XGBClassifier(n_estimators=20, max_depth=2).fit(x, y)
    m.save_model(os.path.join(folder, 'uji.json'))


@pytest.fixture
def app(tmp_path):
    berkas = tmp_path / 'sumber.tsv'
    _tsv(berkas)
    folder_model = tmp_path / 'model'
    folder_model.mkdir()
    _model(folder_model)
    # pengganti foto pegawai SiLAKES: <username SiLAKES>.jpg
    (tmp_path / 'foto_silakes').mkdir()
    (tmp_path / 'foto_silakes' / 'pegawai@lab.jpg').write_bytes(b'\xff\xd8\xff\xe0foto-pegawai')
    app = create_app({'TESTING': True, 'SECRET_KEY': 'kunci-uji',
                      'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(tmp_path / 'uji.db'),
                      'FOLDER_FOTO': str(tmp_path / 'foto'), 'FOLDER_FOTO_UJI': str(tmp_path / 'foto_silakes'),
                      'FOLDER_MODEL': str(folder_model), 'BERKAS_MASTER': str(tmp_path / 'master.json'),
                      'SUMBER_SINKRON': 'berkas', 'BERKAS_SINKRON': str(berkas), 'SINKRON_SEJAK': '2026-11-01'})
    with app.app_context():
        db.create_all()
        sandi = generate_password_hash(KATA_SANDI)
        db.session.add_all([
            Pengguna(nama='Admin Uji', username='admin', kata_sandi=sandi, peran='admin'),
            Pengguna(nama='Petugas Uji', username='petugas', kata_sandi=sandi, peran='petugas'),
            Pengguna(nama='Petugas Nonaktif', username='nonaktif', kata_sandi=sandi, peran='petugas',
                     status_aktif=False),
            ModelDeteksi(versi='uji', ambang=0.5, tanggal_latih=date(2026, 11, 6), roc_auc_validasi=0.75,
                         status_aktif=True)])
        db.session.commit()
    yield app


@pytest.fixture
def klien(app):
    return app.test_client()


def token(klien, username):
    r = klien.post('/api/auth/masuk', json={'username': username, 'kata_sandi': KATA_SANDI})
    assert r.status_code == 200, r.get_json()
    return {'Authorization': 'Bearer ' + r.get_json()['token']}
