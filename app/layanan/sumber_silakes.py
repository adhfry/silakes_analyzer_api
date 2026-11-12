"""Sumber data sinkronisasi.

SumberSsh membaca SiLAKES produksi melalui SSH dengan sesi `SET SESSION TRANSACTION READ ONLY`, sehingga
server basis data sendiri yang menolak setiap perintah tulis. Kueri juga diperiksa sebelum dikirim.
Yang diambil hanya nomor surat, kode pasien yang disamarkan (SHA-256 dengan garam rahasia), tanggal,
jenis kelamin, umur, dan teks hasil enam parameter panel. Nama, NIK, alamat, telepon, dan tanggal lahir
tidak pernah diambil.

Satuan dan nilai rujukan dibaca dari tabel pemeriksaans dan reference_ranges, juga dengan akses baca saja.
Foto akun pengguna prototipe dibaca dari data pegawai SiLAKES (kolom users.foto dan berkasnya), juga baca saja.

SumberBerkas membaca TSV dengan kolom yang sama. Dipakai untuk pengujian otomatis.
"""
import csv
import os
import re
import shlex
import subprocess

from .rujukan import KUNCI as KUNCI_RUJUKAN

# ID pemeriksaan SiLAKES untuk enam parameter panel (tabel pemeriksaans).
ID_PEMERIKSAAN = {'kolesterol_total': 22, 'hdl': 23, 'ldl': 24, 'trigliserida': 25, 'urea': 28, 'kreatinin': 29}
KOLOM = ['id_surat_silakes', 'kode_pasien', 'tanggal_periksa', 'jenis_kelamin', 'umur'] + list(ID_PEMERIKSAAN)

_KATA_TULIS = re.compile(r'(?i)\b(insert|update|delete|drop|alter|create|truncate|replace|grant|into\s+outfile|'
                         r'into\s+dumpfile)\b')
_AWAL_BACA = re.compile(r'(?is)^(select|set\s+@)\b')


class GalatSumber(Exception):
    pass


def periksa_baca_saja(sql):
    for stmt in [s.strip() for s in sql.split(';') if s.strip()]:
        if not _AWAL_BACA.match(stmt) or _KATA_TULIS.search(stmt):
            raise GalatSumber('Kueri ditolak karena bukan kueri baca: ' + stmt[:60])


def kueri_profil(garam, sejak, berubah_sejak=None):
    """Surat completed/approved bertanggal >= sejak. Bila berubah_sejak diisi (waktu WIB, sama dengan kolom
    updated_at SiLAKES), hanya surat yang dibuat atau diubah sesudah waktu itu yang dibaca, sehingga sinkronisasi
    berikutnya hanya membaca surat hasil baru."""
    if not re.fullmatch(r'[0-9a-f]{32,128}', garam or ''):
        raise GalatSumber('GARAM_PASIEN belum diatur (harus heksadesimal 32 sampai 128 karakter).')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', sejak):
        raise GalatSumber('Tanggal awal sinkronisasi tidak valid: ' + sejak)
    if berubah_sejak is not None and not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', berubah_sejak):
        raise GalatSumber('Batas waktu sinkronisasi tidak valid: ' + berubah_sejak)
    syarat_waktu = f" AND s.updated_at >= '{berubah_sejak}'" if berubah_sejak else ''
    kolom = ',\n  '.join("MAX(CASE WHEN h.pemeriksaan_id = %d AND h.is_selected_result = 1 THEN TRIM(h.hasil) END) "
                         "AS %s" % (pid, nama) for nama, pid in ID_PEMERIKSAAN.items())
    return f"""SET @g = '{garam}';
SELECT
  s.id AS id_surat_silakes,
  LEFT(SHA2(CONCAT(@g, 'p', COALESCE(pt.merged_into_id, pt.id)), 256), 16) AS kode_pasien,
  DATE(s.tanggal) AS tanggal_periksa,
  pt.gender AS jenis_kelamin,
  TIMESTAMPDIFF(YEAR, pt.tgl_lahir, s.tanggal) AS umur,
  {kolom}
FROM surat_hasil_labs s
JOIN patients pt ON pt.id = s.patient_id
LEFT JOIN hasil_labs h ON h.surat_hasil_lab_id = s.id
WHERE s.tanggal >= '{sejak}' AND s.status = 'completed' AND s.status_konfirmasi = 'approved'{syarat_waktu}
GROUP BY s.id, s.tanggal, pt.id, pt.merged_into_id, pt.gender, pt.tgl_lahir
ORDER BY s.id;
"""


def kueri_master():
    daftar = ','.join(str(i) for i in ID_PEMERIKSAAN.values())
    return f'SELECT id, name, satuan, nilai_rujukan FROM pemeriksaans WHERE id IN ({daftar}) ORDER BY id;'


def kueri_rujukan():
    kunci = "','".join(KUNCI_RUJUKAN.values())
    return ("SELECT parameter_key, IFNULL(gender, '') AS gender, age_min_years, age_max_years, age_min_days, "
            "age_max_days, value_min, value_max, min_inclusive, max_inclusive, category, category_label, "
            f"severity_rank, sort_order FROM reference_ranges WHERE is_active = 1 AND parameter_key IN ('{kunci}') "
            "ORDER BY parameter_key, sort_order;")


_AKUN_SILAKES = re.compile(r'[a-z0-9._@-]{3,60}')
# Pola jalur foto pegawai SiLAKES (UserManagementController::updatePhoto, disk public).
_JALUR_FOTO = re.compile(r'foto/foto_[0-9a-f-]{36}\.(jpg|jpeg|png|webp)')


def kueri_foto_pegawai(akun):
    """Jalur foto pegawai aktif pada tabel users SiLAKES. Kolom lain (NIP, telepon, alamat) tidak dibaca."""
    if not _AKUN_SILAKES.fullmatch(akun or ''):
        raise GalatSumber('Username SiLAKES tidak valid: ' + str(akun)[:60])
    return f"SELECT foto FROM users WHERE username = '{akun}' AND is_active = 1 LIMIT 1;"


class SumberSsh:
    """Host kosong atau 'lokal': layanan berjalan di server SiLAKES sendiri (produksi), sehingga perintah yang
    sama dijalankan langsung tanpa SSH. Pengamanan baca saja tidak berubah."""

    def __init__(self, host, berkas_env, garam):
        self.host, self.berkas_env, self.garam = host, berkas_env, garam
        self.lokal = (host or 'lokal') == 'lokal'

    def _perintah(self, skrip):
        if self.lokal:
            return ['bash', '-c', skrip]
        return ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20', self.host, 'bash -c ' + shlex.quote(skrip)]

    def _jalankan(self, sql):
        periksa_baca_saja(sql)
        jarak_jauh = (
            f"E={shlex.quote(self.berkas_env)}\n"
            "P=$(grep -E '^DB_PASSWORD=' $E | cut -d= -f2- | sed 's/^\"//; s/\"$//')\n"
            "U=$(grep -E '^DB_USERNAME=' $E | cut -d= -f2-)\n"
            "D=$(grep -E '^DB_DATABASE=' $E | cut -d= -f2-)\n"
            'MYSQL_PWD="$P" mysql -h127.0.0.1 -u"$U" "$D" --default-character-set=utf8mb4 --batch '
            '-e "SET SESSION TRANSACTION READ ONLY; $(cat)"\n')
        try:
            r = subprocess.run(self._perintah(jarak_jauh), input=sql.encode('utf-8'), capture_output=True,
                               timeout=600)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise GalatSumber('Tidak dapat terhubung ke server SiLAKES: %s' % e)
        if r.returncode:
            raise GalatSumber('Kueri SiLAKES gagal: ' + r.stderr.decode('utf-8', 'replace').strip()[-300:])
        baris = [b for b in r.stdout.decode('utf-8', 'replace').splitlines() if b.strip()]
        if not baris:
            return []
        kepala = baris[0].split('\t')
        return [dict(zip(kepala, b.split('\t'))) for b in baris[1:]]

    def ambil_profil(self, sejak, berubah_sejak=None):
        return self._jalankan(kueri_profil(self.garam, sejak, berubah_sejak))

    def ambil_master(self):
        return self._jalankan(kueri_master())

    def ambil_rujukan(self):
        return self._jalankan(kueri_rujukan())

    def ambil_foto_pegawai(self, akun):
        """Membaca berkas foto pegawai dari penyimpanan publik SiLAKES dengan `cat` (baca saja).
        Mengembalikan (isi berkas, ekstensi)."""
        baris = self._jalankan(kueri_foto_pegawai(akun))
        jalur = baris[0]['foto'] if baris else ''
        if not _JALUR_FOTO.fullmatch(jalur):
            raise GalatSumber('Akun SiLAKES %s tidak ditemukan, tidak aktif, atau belum memiliki foto.' % akun)
        lengkap = self.berkas_env.rsplit('/', 1)[0] + '/storage/app/public/' + jalur
        try:
            r = subprocess.run(self._perintah('cat ' + shlex.quote(lengkap)), capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise GalatSumber('Tidak dapat terhubung ke server SiLAKES: %s' % e)
        if r.returncode or not r.stdout:
            raise GalatSumber('Berkas foto tidak dapat dibaca: ' + r.stderr.decode('utf-8', 'replace').strip()[-200:])
        return r.stdout, jalur.rsplit('.', 1)[1]


class SumberBerkas:
    def __init__(self, path, folder_foto=None):
        self.path, self.folder_foto = path, folder_foto

    def ambil_foto_pegawai(self, akun):
        """Pengganti foto pegawai untuk pengujian: <folder_foto>/<username SiLAKES>.jpg."""
        if not _AKUN_SILAKES.fullmatch(akun or ''):
            raise GalatSumber('Username SiLAKES tidak valid: ' + str(akun)[:60])
        path = os.path.join(self.folder_foto or '', akun + '.jpg')
        if not self.folder_foto or not os.path.isfile(path):
            raise GalatSumber('Akun SiLAKES %s tidak ditemukan, tidak aktif, atau belum memiliki foto.' % akun)
        with open(path, 'rb') as f:
            return f.read(), 'jpg'

    def ambil_profil(self, sejak, berubah_sejak=None):
        # Berkas uji tidak memiliki kolom waktu perubahan; seluruh baris sejak tanggal awal dibaca.
        with open(self.path, encoding='utf-8', newline='') as f:
            return [b for b in csv.DictReader(f, delimiter='\t') if b['tanggal_periksa'] >= sejak]

    def ambil_master(self):
        return []

    def ambil_rujukan(self):
        return []
