from conftest import KATA_SANDI, token


def sinkron(klien):
    return klien.post('/api/admin/sinkronisasi', headers=token(klien, 'admin'))


def test_masuk_benar_dan_salah(klien):
    assert klien.post('/api/auth/masuk', json={'username': 'petugas', 'kata_sandi': 'salah'}).status_code == 401
    assert klien.post('/api/auth/masuk', json={'username': '', 'kata_sandi': ''}).status_code == 400
    r = klien.post('/api/auth/masuk', json={'username': 'PETUGAS', 'kata_sandi': KATA_SANDI})
    assert r.status_code == 200 and r.get_json()['pengguna']['peran'] == 'petugas'


def test_akun_nonaktif_ditolak(klien):
    r = klien.post('/api/auth/masuk', json={'username': 'nonaktif', 'kata_sandi': KATA_SANDI})
    assert r.status_code == 403


def test_tanpa_token_dan_token_rusak(klien):
    assert klien.get('/api/ringkasan').status_code == 401
    assert klien.get('/api/ringkasan', headers={'Authorization': 'Bearer abc'}).status_code == 401


def test_petugas_tidak_bisa_membuka_menu_admin(klien):
    h = token(klien, 'petugas')
    assert klien.get('/api/admin/pengguna', headers=h).status_code == 403
    assert klien.post('/api/admin/sinkronisasi', headers=h).status_code == 403


def test_sinkronisasi_mengikuti_aturan_persiapan(klien):
    r = sinkron(klien)
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d['surat_dibaca'] == 8          # surat 900 sebelum tanggal awal tidak dibaca
    assert d['profil_diproses'] == 5
    assert d['dilewati'] == {'umur_tidak_valid': 1, 'panel_tidak_lengkap': 2}
    assert d['perlu_ditinjau'] + d['tidak_ada_indikasi'] == 5
    # Sinkronisasi kedua tidak memproses ulang surat yang sudah tersimpan.
    d2 = sinkron(klien).get_json()
    assert d2['surat_baru'] == 3 and d2['profil_diproses'] == 0


def test_daftar_detail_dan_tindak_lanjut(klien):
    sinkron(klien)
    h = token(klien, 'petugas')
    daftar = klien.get('/api/deteksi', headers=h).get_json()
    assert daftar['total'] == 5
    peluang = [x['peluang_anomali'] for x in daftar['data']]
    assert peluang == sorted(peluang, reverse=True)
    assert klien.get('/api/deteksi?cari=1002', headers=h).get_json()['total'] == 1
    assert klien.get('/api/deteksi?status=lain', headers=h).status_code == 400
    assert daftar['jumlah_status']['semua'] == 5
    assert daftar['rentang_tanggal'] == ['2026-11-01', '2026-11-05']

    id_deteksi = daftar['data'][0]['id_deteksi']
    detail = klien.get('/api/deteksi/%d' % id_deteksi, headers=h).get_json()
    assert len(detail['panel']) == 6 and len(detail['kontribusi']) == 8
    assert [b['no'] for b in detail['panel']] == [1, 2, 3, 4, 5, 6]
    assert [k['peringkat'] for k in detail['kontribusi']] == list(range(1, 9))
    # Sifat aditif SHAP: nilai dasar + jumlah kontribusi = keluaran log-odds; sigmoid-nya = peluang.
    import math
    assert abs(1 / (1 + math.exp(-detail['keluaran_log_odds'])) - detail['peluang_anomali']) < 2e-3

    assert klien.post('/api/deteksi/%d/tindak-lanjut' % id_deteksi, headers=h,
                      json={'keputusan': 'asal'}).status_code == 400
    r = klien.post('/api/deteksi/%d/tindak-lanjut' % id_deteksi, headers=h,
                   json={'keputusan': 'pemeriksaan_ulang', 'catatan': 'Kreatinin turun jauh.'})
    assert r.status_code == 201
    ringkasan = klien.get('/api/ringkasan', headers=h).get_json()
    assert ringkasan['total'] == 5 and ringkasan['sudah_ditindaklanjuti'] == 1
    assert klien.get('/api/deteksi/999', headers=h).status_code == 404


def test_admin_kelola_pengguna(klien):
    h = token(klien, 'admin')
    assert klien.post('/api/admin/pengguna', headers=h,
                      json={'nama': 'A', 'username': 'x', 'peran': 'petugas', 'kata_sandi': '12345678'}).status_code == 400
    r = klien.post('/api/admin/pengguna', headers=h,
                   json={'nama': 'Siti', 'username': 'siti', 'peran': 'petugas', 'kata_sandi': '12345678'})
    assert r.status_code == 201
    baru = r.get_json()['id_pengguna']
    assert klien.post('/api/admin/pengguna', headers=h,
                      json={'nama': 'Siti', 'username': 'siti', 'peran': 'petugas',
                            'kata_sandi': '12345678'}).status_code == 409
    assert klien.put('/api/admin/pengguna/%d' % baru, headers=h, json={'status_aktif': False}).status_code == 200
    assert klien.post('/api/auth/masuk', json={'username': 'siti', 'kata_sandi': '12345678'}).status_code == 403


def test_token_akun_yang_dinonaktifkan_langsung_ditolak(klien):
    hp = token(klien, 'petugas')
    ha = token(klien, 'admin')
    id_petugas = klien.get('/api/auth/saya', headers=hp).get_json()['id_pengguna']
    klien.put('/api/admin/pengguna/%d' % id_petugas, headers=ha, json={'status_aktif': False})
    assert klien.get('/api/ringkasan', headers=hp).status_code == 401


def test_admin_tidak_bisa_mengunci_diri(klien):
    h = token(klien, 'admin')
    saya = klien.get('/api/auth/saya', headers=h).get_json()['id_pengguna']
    assert klien.put('/api/admin/pengguna/%d' % saya, headers=h, json={'status_aktif': False}).status_code == 400
    assert klien.put('/api/admin/pengguna/%d' % saya, headers=h, json={'peran': 'petugas'}).status_code == 400


def test_ambang(klien):
    h = token(klien, 'admin')
    assert klien.get('/api/admin/ambang', headers=h).get_json()['ambang'] == 0.5
    for salah in (-0.1, 1.5, 'a', True, None):
        assert klien.put('/api/admin/ambang', headers=h, json={'ambang': salah}).status_code == 400
    assert klien.put('/api/admin/ambang', headers=h, json={'ambang': 0.35}).get_json()['ambang'] == 0.35
    # Ambang 0 membuat semua profil berikutnya berstatus perlu ditinjau (peluang > 0).
    klien.put('/api/admin/ambang', headers=h, json={'ambang': 0})
    assert sinkron(klien).get_json()['perlu_ditinjau'] == 5


def test_ringkasan_admin_memuat_sinkronisasi_terakhir(klien):
    sinkron(klien)
    d = klien.get('/api/admin/ringkasan', headers=token(klien, 'admin')).get_json()
    s = d['sinkronisasi_terakhir']
    assert s['status'] == 'berhasil' and s['jumlah_profil'] == 5
    assert s['perlu_ditinjau'] + s['tidak_ada_indikasi'] == 5


def test_klasifikasi_rujukan_sama_dengan_silakes():
    from app.layanan import rujukan
    baris = rujukan.baris_dari_kueri([
        dict(parameter_key='hdl', gender='P', age_min_years='18', age_max_years='', age_min_days='', age_max_days='',
             value_min='', value_max='50', min_inclusive='0', max_inclusive='0', category='low', category_label='Low',
             severity_rank='1', sort_order='1'),
        dict(parameter_key='hdl', gender='P', age_min_years='18', age_max_years='', age_min_days='', age_max_days='',
             value_min='50', value_max='', min_inclusive='1', max_inclusive='1', category='acceptable',
             category_label='Acceptable', severity_rank='0', sort_order='2'),
        dict(parameter_key='hdl', gender='L', age_min_years='18', age_max_years='', age_min_days='', age_max_days='',
             value_min='40', value_max='', min_inclusive='1', max_inclusive='1', category='acceptable',
             category_label='Acceptable', severity_rank='0', sort_order='3')])
    assert rujukan.klasifikasi(baris, 'hdl', 45, 'P', 40) == {'rujukan': '>= 50', 'keterangan': 'rendah',
                                                              'kategori': 'Low'}
    assert rujukan.klasifikasi(baris, 'hdl', 50, 'P', 40)['keterangan'] == 'sesuai'
    assert rujukan.klasifikasi(baris, 'hdl', 45, 'L', 40)['keterangan'] == 'sesuai'
    assert rujukan.klasifikasi(baris, 'hdl', 45, 'P', 10) is None


def test_sinkronisasi_tanpa_surat_baru(app):
    """Bila sumber tidak mengembalikan surat, sinkronisasi berhasil dan melaporkan tidak ada data baru."""
    from app.ekstensi import db
    from app.layanan import sinkronisasi
    from app.models import Pengguna

    class Kosong:
        batas = 'belum dipanggil'

        def ambil_profil(self, sejak, berubah_sejak=None):
            Kosong.batas = berubah_sejak
            return []

        def ambil_master(self):
            return []

        def ambil_rujukan(self):
            return []

    with app.app_context():
        admin = Pengguna.query.filter_by(username='admin').first()
        d = sinkronisasi.jalankan(Kosong(), admin, app.config['FOLDER_MODEL'], '2026-11-01')
        assert d['ada_data_baru'] is False and d['profil_diproses'] == 0 and d['log']['status'] == 'berhasil'
        assert Kosong.batas is None             # sinkronisasi pertama membaca sejak tanggal awal
        sinkronisasi.jalankan(Kosong(), admin, app.config['FOLDER_MODEL'], '2026-11-01')
        assert Kosong.batas is not None         # berikutnya hanya surat yang berubah sejak sinkronisasi terakhir


def test_status_memakai_lebih_dari_ambang():
    from app.layanan.model_deteksi import status_dari
    assert status_dari(0.5001, 0.5) == 'perlu_ditinjau'
    assert status_dari(0.5, 0.5) == 'tidak_ada_indikasi'
    assert status_dari(0.4999, 0.5) == 'tidak_ada_indikasi'


def test_nilai_dasar_aditif_sejak_model_dimuat(app, tmp_path):
    """Nilai dasar SHAP harus memenuhi phi_0 + jumlah phi_j = log-odds walau dibaca sebelum prediksi apa pun.

    Memakai model akhir penelitian (S2) bila tersedia, karena pada model itu taksiran awal TreeExplainer
    berbeda 0,0038 dari nilai dasar yang sebenarnya.
    """
    import math
    import os
    import shutil
    from app.layanan import model_deteksi
    asli = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'penelitian', 'hasil', 'S2', 'model.json')
    folder, versi = app.config['FOLDER_MODEL'], 'uji'
    if os.path.exists(asli):
        shutil.copyfile(asli, os.path.join(folder, 's2.json'))
        versi = 's2'
    model_deteksi._muat.cache_clear()
    dasar = model_deteksi.nilai_dasar(folder, versi)
    profil = [{'kolesterol_total': 200, 'hdl': 45, 'ldl': 120, 'trigliserida': 150, 'urea': 30, 'kreatinin': 0.9,
               'jenis_kelamin': 'L', 'umur': 50}]
    peluang, nilai, _ = model_deteksi.prediksi(folder, versi, profil)
    p = float(peluang[0])
    assert abs(math.log(p / (1 - p)) - (dasar + float(nilai[0].sum()))) < 1e-4


def test_kueri_baca_saja_menolak_kata_tulis():
    import pytest
    from app.layanan.sumber_silakes import GalatSumber, kueri_profil, periksa_baca_saja
    with pytest.raises(GalatSumber):
        periksa_baca_saja('SELECT 1; DELETE FROM patients')
    with pytest.raises(GalatSumber):
        kueri_profil('', '2026-11-01')
    periksa_baca_saja(kueri_profil('ab' * 16, '2026-11-01'))


def test_akun_baru_ditautkan_ke_pegawai_silakes_dan_reset_sandi(klien):
    ha = token(klien, 'admin')
    data = {'nama': 'Pegawai Lab', 'username': 'pegawai', 'peran': 'petugas', 'kata_sandi': 'sandi-awal-1',
            'akun_silakes': 'Pegawai@Lab'}
    # username SiLAKES yang tidak ada ditolak dan akun tidak dibuat
    r = klien.post('/api/admin/pengguna', json={**data, 'akun_silakes': 'tidakada@lab'}, headers=ha)
    assert r.status_code == 400 and 'tidak ditemukan' in r.get_json()['galat']
    assert all(p['username'] != 'pegawai' for p in klien.get('/api/admin/pengguna', headers=ha).get_json())
    r = klien.post('/api/admin/pengguna', json=data, headers=ha)
    assert r.status_code == 201, r.get_json()
    p = r.get_json()
    assert p['akun_silakes'] == 'pegawai@lab' and p['ada_foto'] is True
    assert klien.get('/api/pengguna/%d/foto' % p['id_pengguna'], headers=ha).data.endswith(b'foto-pegawai')
    # reset kata sandi oleh admin: kata sandi lama tidak berlaku lagi
    r = klien.put('/api/admin/pengguna/%d' % p['id_pengguna'], json={'kata_sandi': 'sandi-baru-22'}, headers=ha)
    assert r.status_code == 200
    assert klien.post('/api/auth/masuk', json={'username': 'pegawai', 'kata_sandi': 'sandi-awal-1'}).status_code == 401
    assert klien.post('/api/auth/masuk', json={'username': 'pegawai', 'kata_sandi': 'sandi-baru-22'}).status_code == 200


def test_foto_akun_hanya_untuk_pemilik_dan_admin(app, klien, tmp_path):
    import pytest
    from app.layanan.sumber_silakes import GalatSumber, kueri_foto_pegawai, periksa_baca_saja
    from app.ekstensi import db
    from app.models import Pengguna
    # kueri foto pegawai hanya membaca kolom foto dan menolak username yang dapat menyisipkan SQL
    periksa_baca_saja(kueri_foto_pegawai('jazilah@labkesmas'))
    with pytest.raises(GalatSumber):
        kueri_foto_pegawai("x' OR '1'='1")
    folder = tmp_path / 'foto'
    folder.mkdir()
    (folder / 'petugas.jpg').write_bytes(b'\xff\xd8\xff\xe0uji')
    app.config['FOLDER_FOTO'] = str(folder)
    with app.app_context():
        petugas = Pengguna.query.filter_by(username='petugas').first()
        petugas.foto = 'petugas.jpg'
        db.session.commit()
        id_petugas = petugas.id_pengguna
        id_admin = Pengguna.query.filter_by(username='admin').first().id_pengguna
    hp = token(klien, 'petugas')
    assert klien.get('/api/auth/saya', headers=hp).get_json()['ada_foto'] is True
    r = klien.get('/api/pengguna/%d/foto' % id_petugas, headers=hp)
    assert r.status_code == 200 and r.data.startswith(b'\xff\xd8')
    assert klien.get('/api/pengguna/%d/foto' % id_admin, headers=hp).status_code == 403
    ha = token(klien, 'admin')
    assert klien.get('/api/pengguna/%d/foto' % id_petugas, headers=ha).status_code == 200
    assert klien.get('/api/pengguna/%d/foto' % id_admin, headers=ha).status_code == 404
    assert klien.get('/api/pengguna/%d/foto' % id_petugas).status_code == 401
