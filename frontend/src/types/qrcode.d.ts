declare module 'qrcode' {
  const QRCode: {
    toDataURL: (text: string, opts?: Record<string, unknown>) => Promise<string>
  }
  export default QRCode
}
