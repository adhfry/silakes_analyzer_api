"""Sinkronisasi: baca surat hasil baru dari SiLAKES, siapkan profil, jalankan model, simpan hasil deteksi.

Aturan persiapan sama dengan Subbab Persiapan Data pada BAB III dan `penelitian/src/persiapan.py`:
surat berstatus completed dan approved, umur 1 sampai 100 tahun, jenis kelamin L atau P, dan enam nilai
panel berupa angka. Surat yang tidak memenuhi aturan dilewati dan dihitung menurut alasannya.
"""
import json
import re
from datetime import date, datetime, timedelta

from ..ekstensi import db
from ..models import FITUR, PANEL, HasilDeteksi, KontribusiFitur, LogSinkronisasi, ModelDeteksi, ProfilHasil
from . import model_deteksi, rujukan
from .sumber_silakes import ID_PEMERIKSAAN, GalatSumber

_ANGKA = re.compile(r'^\d+([.,]\d+)?$')
BATAS_BERJALAN = timedelta(minutes=15)
# Selisih aman agar surat yang diubah tepat saat sinkronisasi sebelumnya berjalan tetap terbaca.
SELISIH_AMAN = timedelta(minutes=5)


class GalatSinkronisasi(Exception):
    def __init__(self, pesan, kode=500):
        super().__init__(pesan)
        self.kode = kode


def ke_angka(teks):
    t = (teks or '').strip()
    if t in ('', 'NULL') or not _ANGKA.match(t):
        return None
    return float(t.replace(',', '.'))


def siapkan_baris(b):
    """Kembalikan (profil, None) bila memenuhi aturan, atau (None, alasan)."""
    try:
        umur = int(b.get('umur') or '')
    except ValueError:
        return None, 'umur_tidak_valid'
    if not 1 <= umur <= 100:
        return None, 'umur_tidak_valid'
    if b.get('jenis_kelamin') not in ('L', 'P'):
        return None, 'jenis_kelamin_kosong'
    nilai = {p: ke_angka(b.get(p)) for p in PANEL}
    if any(v is None for v in nilai.values()):
        return None, 'panel_tidak_lengkap'
    return {'id_surat_silakes': int(b['id_surat_silakes']), 'kode_pasien': b['kode_pasien'],
            'tanggal_periksa': date.fromisoformat(b['tanggal_periksa']), 'jenis_kelamin': b['jenis_kelamin'],
            'umur': umur, **nilai}, None


def simpan_master(sumber, path):
    """Satuan enam parameter (pemeriksaans) dan baris rentang rujukan (reference_ranges) SiLAKES.

    Keduanya dipakai halaman detail untuk kolom satuan, rujukan, dan keterangan.
    """
    baris = sumber.ambil_master()
    if not baris:
        return
    per_id = {int(b['id']): b for b in baris}
    isi = {p: {'nama': per_id[i]['name'], 'satuan': per_id[i]['satuan'], 'nilai_rujukan': per_id[i]['nilai_rujukan']}
           for p, i in ID_PEMERIKSAAN.items() if i in per_id}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'diambil_pada': datetime.now().isoformat(timespec='seconds'), 'parameter': isi,
                   'rujukan': rujukan.baris_dari_kueri(sumber.ambil_rujukan())}, f, ensure_ascii=False, indent=2)


def jalankan(sumber, pengguna, folder_model, sejak, berkas_master=None):
    model = ModelDeteksi.query.filter_by(status_aktif=True).first()
    if model is None:
        raise GalatSinkronisasi('Belum ada model aktif. Admin perlu mengimpor model terlebih dahulu.', 409)
    berjalan = LogSinkronisasi.query.filter_by(status='berjalan').order_by(LogSinkronisasi.waktu_mulai.desc()).first()
    if berjalan and datetime.now() - berjalan.waktu_mulai < BATAS_BERJALAN:
        raise GalatSinkronisasi('Sinkronisasi lain sedang berjalan sejak %s.' % berjalan.waktu_mulai.strftime('%H:%M'),
                                409)

    sebelumnya = (LogSinkronisasi.query.filter_by(status='berhasil')
                  .order_by(LogSinkronisasi.waktu_mulai.desc()).first())
    berubah_sejak = ((sebelumnya.waktu_mulai - SELISIH_AMAN).strftime('%Y-%m-%d %H:%M:%S')
                     if sebelumnya else None)
    log = LogSinkronisasi(id_pengguna=pengguna.id_pengguna, waktu_mulai=datetime.now(), status='berjalan')
    db.session.add(log)
    db.session.commit()
    try:
        baris = sumber.ambil_profil(sejak, berubah_sejak)
        sudah = {i for (i,) in db.session.query(ProfilHasil.id_surat_silakes)}
        baru = [b for b in baris if int(b['id_surat_silakes']) not in sudah]
        profil, dilewati = [], {}
        for b in baru:
            p, alasan = siapkan_baris(b)
            if p is None:
                dilewati[alasan] = dilewati.get(alasan, 0) + 1
            else:
                profil.append(p)

        perlu = 0
        if profil:
            peluang, nilai_shap, _ = model_deteksi.prediksi(folder_model, model.versi, profil)
            ambang = float(model.ambang)
            waktu = datetime.now()
            for p, pel, sh in zip(profil, peluang, nilai_shap):
                ph = ProfilHasil(diambil_pada=waktu, **p)
                status = model_deteksi.status_dari(float(pel), ambang)
                perlu += status == 'perlu_ditinjau'
                hd = HasilDeteksi(profil=ph, id_model=model.id_model, peluang_anomali=round(float(pel), 4),
                                  status_deteksi=status, waktu_deteksi=waktu)
                urutan = sorted(range(len(FITUR)), key=lambda i: -abs(sh[i]))
                for peringkat, i in enumerate(urutan, start=1):
                    f = FITUR[i]
                    nilai = (1 if p[f] == 'L' else 0) if f == 'jenis_kelamin' else p[f]
                    hd.kontribusi.append(KontribusiFitur(nama_fitur=f, nilai_fitur=nilai,
                                                         nilai_shap=round(float(sh[i]), 4), peringkat=peringkat))
                db.session.add(hd)

        if berkas_master:
            try:
                simpan_master(sumber, berkas_master)
            except GalatSumber:
                pass  # rujukan lama tetap dipakai; sinkronisasi profil tidak perlu digagalkan

        log.jumlah_profil = len(profil)
        log.status = 'berhasil'
        log.waktu_selesai = datetime.now()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        log = db.session.get(LogSinkronisasi, log.id_sinkronisasi)
        log.status = 'gagal'
        log.waktu_selesai = datetime.now()
        db.session.commit()
        if isinstance(e, GalatSumber):
            raise GalatSinkronisasi(str(e), 502) from e
        raise

    return {'log': log.ke_dict(), 'model': model.versi, 'ambang': float(model.ambang), 'sejak': sejak,
            'surat_dibaca': len(baris), 'surat_baru': len(baru), 'profil_diproses': len(profil),
            'dilewati': dilewati, 'perlu_ditinjau': perlu, 'tidak_ada_indikasi': len(profil) - perlu,
            'ada_data_baru': bool(baru)}
