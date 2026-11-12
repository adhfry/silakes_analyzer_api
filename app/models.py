"""Tabel basis data prototipe. Nama tabel, kolom, dan tipe data mengikuti PDM pada BAB III (Gambar PDM)."""
from datetime import datetime

from .ekstensi import db

PANEL = ['kolesterol_total', 'hdl', 'ldl', 'trigliserida', 'urea', 'kreatinin']
FITUR = PANEL + ['jenis_kelamin', 'umur']

PERAN = ('petugas', 'admin')
STATUS_DETEKSI = ('perlu_ditinjau', 'tidak_ada_indikasi')
KEPUTUSAN = ('hasil_sesuai', 'verifikasi_identitas_spesimen', 'pemeriksaan_ulang')


def _waktu(w):
    return w.isoformat(timespec='seconds') if w else None


class Pengguna(db.Model):
    __tablename__ = 'pengguna'
    id_pengguna = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nama = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(50), nullable=False, unique=True)
    kata_sandi = db.Column(db.String(255), nullable=False)
    peran = db.Column(db.String(10), nullable=False)
    status_aktif = db.Column(db.Boolean, nullable=False, default=True)
    dibuat_pada = db.Column(db.DateTime, nullable=False, default=datetime.now)
    # Username pegawai yang sama pada SiLAKES; dipakai untuk mengambil foto pegawai (baca saja).
    akun_silakes = db.Column(db.String(60))
    # Nama berkas foto pegawai di folder instance/foto, disalin dari data pegawai SiLAKES.
    foto = db.Column(db.String(100))

    def ke_dict(self):
        return {'id_pengguna': self.id_pengguna, 'nama': self.nama, 'username': self.username,
                'peran': self.peran, 'status_aktif': self.status_aktif, 'dibuat_pada': _waktu(self.dibuat_pada),
                'akun_silakes': self.akun_silakes, 'ada_foto': bool(self.foto)}


class LogSinkronisasi(db.Model):
    __tablename__ = 'log_sinkronisasi'
    id_sinkronisasi = db.Column(db.Integer, primary_key=True, autoincrement=True)
    id_pengguna = db.Column(db.Integer, db.ForeignKey('pengguna.id_pengguna'), nullable=False, index=True)
    waktu_mulai = db.Column(db.DateTime, nullable=False)
    waktu_selesai = db.Column(db.DateTime)
    jumlah_profil = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False)

    def ke_dict(self):
        return {'id_sinkronisasi': self.id_sinkronisasi, 'id_pengguna': self.id_pengguna,
                'waktu_mulai': _waktu(self.waktu_mulai), 'waktu_selesai': _waktu(self.waktu_selesai),
                'jumlah_profil': self.jumlah_profil, 'status': self.status}


class ModelDeteksi(db.Model):
    __tablename__ = 'model_deteksi'
    id_model = db.Column(db.Integer, primary_key=True, autoincrement=True)
    versi = db.Column(db.String(20), nullable=False, unique=True)
    ambang = db.Column(db.Numeric(4, 3), nullable=False, default=0.5)
    tanggal_latih = db.Column(db.Date, nullable=False)
    roc_auc_validasi = db.Column(db.Numeric(5, 4), nullable=False)
    status_aktif = db.Column(db.Boolean, nullable=False, default=False)

    def ke_dict(self):
        return {'id_model': self.id_model, 'versi': self.versi, 'ambang': float(self.ambang),
                'tanggal_latih': self.tanggal_latih.isoformat(), 'roc_auc_validasi': float(self.roc_auc_validasi),
                'status_aktif': self.status_aktif}


class ProfilHasil(db.Model):
    __tablename__ = 'profil_hasil'
    id_profil = db.Column(db.Integer, primary_key=True, autoincrement=True)
    # Nomor surat hasil di SiLAKES. Bukan kunci asing karena berada pada basis data yang berbeda.
    id_surat_silakes = db.Column(db.Integer, nullable=False, unique=True)
    kode_pasien = db.Column(db.String(64), nullable=False, index=True)
    tanggal_periksa = db.Column(db.Date, nullable=False)
    jenis_kelamin = db.Column(db.String(1), nullable=False)
    umur = db.Column(db.Integer, nullable=False)
    kolesterol_total = db.Column(db.Numeric(8, 2), nullable=False)
    hdl = db.Column(db.Numeric(8, 2), nullable=False)
    ldl = db.Column(db.Numeric(8, 2), nullable=False)
    trigliserida = db.Column(db.Numeric(8, 2), nullable=False)
    urea = db.Column(db.Numeric(8, 2), nullable=False)
    kreatinin = db.Column(db.Numeric(8, 2), nullable=False)
    diambil_pada = db.Column(db.DateTime, nullable=False, default=datetime.now)

    def ke_dict(self):
        d = {'id_profil': self.id_profil, 'id_surat_silakes': self.id_surat_silakes, 'kode_pasien': self.kode_pasien,
             'tanggal_periksa': self.tanggal_periksa.isoformat(), 'jenis_kelamin': self.jenis_kelamin,
             'umur': self.umur, 'diambil_pada': _waktu(self.diambil_pada)}
        d.update({p: float(getattr(self, p)) for p in PANEL})
        return d


class HasilDeteksi(db.Model):
    __tablename__ = 'hasil_deteksi'
    id_deteksi = db.Column(db.Integer, primary_key=True, autoincrement=True)
    id_profil = db.Column(db.Integer, db.ForeignKey('profil_hasil.id_profil'), nullable=False, index=True)
    id_model = db.Column(db.Integer, db.ForeignKey('model_deteksi.id_model'), nullable=False, index=True)
    peluang_anomali = db.Column(db.Numeric(5, 4), nullable=False)
    status_deteksi = db.Column(db.String(20), nullable=False, index=True)
    waktu_deteksi = db.Column(db.DateTime, nullable=False, default=datetime.now)

    profil = db.relationship('ProfilHasil')
    model = db.relationship('ModelDeteksi')
    kontribusi = db.relationship('KontribusiFitur', order_by='KontribusiFitur.peringkat', cascade='all, delete-orphan')
    tindak_lanjut = db.relationship('TindakLanjut', order_by='TindakLanjut.dicatat_pada.desc()')


class KontribusiFitur(db.Model):
    __tablename__ = 'kontribusi_fitur'
    id_kontribusi = db.Column(db.Integer, primary_key=True, autoincrement=True)
    id_deteksi = db.Column(db.Integer, db.ForeignKey('hasil_deteksi.id_deteksi'), nullable=False, index=True)
    nama_fitur = db.Column(db.String(30), nullable=False)
    nilai_fitur = db.Column(db.Numeric(8, 2), nullable=False)
    nilai_shap = db.Column(db.Numeric(8, 4), nullable=False)
    peringkat = db.Column(db.Integer, nullable=False)

    def ke_dict(self):
        return {'nama_fitur': self.nama_fitur, 'nilai_fitur': float(self.nilai_fitur),
                'nilai_shap': float(self.nilai_shap), 'peringkat': self.peringkat}


class TindakLanjut(db.Model):
    __tablename__ = 'tindak_lanjut'
    id_tindak_lanjut = db.Column(db.Integer, primary_key=True, autoincrement=True)
    id_deteksi = db.Column(db.Integer, db.ForeignKey('hasil_deteksi.id_deteksi'), nullable=False, index=True)
    id_pengguna = db.Column(db.Integer, db.ForeignKey('pengguna.id_pengguna'), nullable=False, index=True)
    keputusan = db.Column(db.String(30), nullable=False)
    catatan = db.Column(db.Text)
    dicatat_pada = db.Column(db.DateTime, nullable=False, default=datetime.now)

    pengguna = db.relationship('Pengguna')

    def ke_dict(self):
        return {'id_tindak_lanjut': self.id_tindak_lanjut, 'id_deteksi': self.id_deteksi,
                'keputusan': self.keputusan, 'catatan': self.catatan, 'dicatat_pada': _waktu(self.dicatat_pada),
                'pengguna': {'id_pengguna': self.pengguna.id_pengguna, 'nama': self.pengguna.nama}}
