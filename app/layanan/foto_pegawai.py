"""Menautkan akun prototipe dengan data pegawai SiLAKES: foto pegawai dibaca (baca saja) lalu disimpan di
folder instance/foto dengan nama <username prototipe>.<ekstensi>."""
import os

from .sumber_silakes import GalatSumber  # noqa: F401  (diteruskan ke pemanggil)


def simpan_foto(pengguna, akun_silakes, sumber, folder):
    """Ambil foto pegawai SiLAKES untuk `pengguna`. Melempar GalatSumber bila akun SiLAKES tidak ditemukan."""
    isi, ext = sumber.ambil_foto_pegawai(akun_silakes)
    os.makedirs(folder, exist_ok=True)
    lama = pengguna.foto
    nama = '%s.%s' % (pengguna.username, ext)
    with open(os.path.join(folder, nama), 'wb') as f:
        f.write(isi)
    if lama and lama != nama and os.path.isfile(os.path.join(folder, lama)):
        os.remove(os.path.join(folder, lama))
    pengguna.akun_silakes = akun_silakes
    pengguna.foto = nama
    return len(isi)
