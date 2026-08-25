export const SLASH_COMMANDS = [
  { cmd: '/events', label: 'Event terbaru', insert: 'Tampilkan event pelanggaran/darurat terbaru.' },
  { cmd: '/pending', label: 'Insiden belum ditinjau', insert: 'Tampilkan insiden yang masih berstatus PENDING.' },
  { cmd: '/confirmed', label: 'Insiden terkonfirmasi', insert: 'Tampilkan insiden yang sudah CONFIRMED beserta status tindakannya.' },
  { cmd: '/ringkasan', label: 'Ringkasan keselamatan', insert: 'Ringkas kondisi keselamatan pabrik saat ini.' },
  { cmd: '/laporan', label: 'Laporan 24 jam terakhir', insert: 'Buatkan laporan keselamatan untuk 24 jam terakhir.' },
  { cmd: '/laporan-minggu', label: 'Laporan mingguan', insert: 'Buatkan laporan keselamatan untuk 7 hari terakhir.' },
  { cmd: '/notifikasi', label: 'Log notifikasi', insert: 'Tampilkan log notifikasi yang sudah dikirim.' },
  { cmd: '/zona', label: 'Konfigurasi zona', insert: 'Tampilkan konfigurasi aturan tiap zona.' },
  { cmd: '/status', label: 'Status stream/kamera', insert: 'Cek status semua stream dan kamera.' },
  { cmd: '/sistem', label: 'Konfigurasi sistem', insert: 'Cek model deteksi aktif dan confidence threshold saat ini.' },
  { cmd: '/kirim', label: 'Kirim pesan ke channel safety', insert: 'Kirim pesan ke channel safety: ' },
  { cmd: '/pause', label: 'Pause/resume kamera', insert: 'Pause kamera ' },
  { cmd: '/confidence', label: 'Ubah confidence threshold', insert: 'Ubah confidence threshold ke ' },
  { cmd: '/model', label: 'Ganti model deteksi', insert: 'Ganti model deteksi ke ' },
];

export function filterSlashCommands(query) {
  const q = query.toLowerCase();
  return SLASH_COMMANDS.filter((c) => c.cmd.toLowerCase().includes(q) || c.label.toLowerCase().includes(q));
}
