/**
 * electron-builder afterPack hook:
 * Disables ASAR integrity fuse in the Electron binary.
 * This prevents silent crashes on arm64 macOS when the
 * ASAR hash doesn't match (which happens with ad-hoc signing).
 */
const { join } = require('path')
const { flipFuses, FuseVersion, FuseV1Options } = require('@electron/fuses')

exports.default = async function (context) {
  const appPath = join(
    context.appOutDir,
    `${context.packager.appInfo.productFilename}.app`
  )
  const electronBinary = join(
    appPath,
    'Contents',
    'MacOS',
    context.packager.appInfo.productFilename
  )

  console.log('  • flipping ASAR integrity fuse off...')

  await flipFuses(electronBinary, {
    version: FuseVersion.V1,
    [FuseV1Options.EnableEmbeddedAsarIntegrityValidation]: false,
  })

  console.log('  • ASAR integrity fuse disabled')
}
