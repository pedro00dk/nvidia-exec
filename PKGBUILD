# Maintainer: Pedro Henrique <pedro00dk@gmail.com>
pkgname=nvidia-exec
pkgver=0.0.3
pkgrel=1
pkgdesc="Run programs in nvidia optimus setups with power management for Xorg and Wayland without log out"
arch=("x86_64")
url="https://github.com/pedro00dk/nvidia-exec#readme"
license=('GPL')
depends=('nvidia' 'lshw' 'jq')
source=("${pkgname}-${pkgver}.tar.gz::https://github.com/pedro00dk/nvidia-exec/archive/refs/tags/v${pkgver}.tar.gz")
sha256sums=('84f79ad3ee9fac668edfaf8a9b06b1b84727cb1b4bf6981ccaeb512c7fc362e5')

package() {
    cd "${pkgname}-${pkgver}"
    install -Dm 755 nvx "$pkgdir/usr/bin/nvx"
    install -Dm 644 nvx.service "$pkgdir/usr/lib/systemd/system/nvx.service"
    install -Dm 644 modprobe.conf "$pkgdir/usr/lib/modprobe.d/nvx.conf"
}
