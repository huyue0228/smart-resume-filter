export default function BrandLogo({ size = 32, className }) {
  return (
    <img
      src="/favicon.svg"
      alt="海纳智选标志"
      className={className}
      width={size}
      height={size}
    />
  )
}
