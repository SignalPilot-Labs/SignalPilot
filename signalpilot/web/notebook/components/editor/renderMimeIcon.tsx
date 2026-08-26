export function renderMimeIcon(mime: string) {
  switch (mime) {
    case "text/html":
      return "🌐";
    case "text/plain":
      return "📄";
    case "application/json":
      return "📦";
    case "image/png":
    case "image/tiff":
    case "image/avif":
    case "image/bmp":
    case "image/gif":
    case "image/jpeg":
      return "🖼️";
    case "image/svg+xml":
      return "🎨";
    case "video/mp4":
    case "video/mpeg":
      return "🎥";
    case "application/vnd.sp+error":
      return "🚨";
    case "application/vnd.sp+traceback":
      return "🐍";
    case "text/csv":
      return "📊";
    case "text/markdown":
      return "📝";
    case "application/vnd.vegalite.v5+json":
    case "application/vnd.vega.v5+json":
    case "application/vnd.vegalite.v6+json":
    case "application/vnd.vega.v6+json":
      return "📊";
    case "application/vnd.sp+mimebundle":
      return "📦";
    default:
      return "❓";
  }
}
