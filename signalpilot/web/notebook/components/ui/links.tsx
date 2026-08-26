export const ExternalLink = ({
  href,
  children,
}: {
  href:
    | `https://platform.openai.com/${string}`
    | `https://console.anthropic.com/${string}`
    | `https://aistudio.google.com/${string}`
    | `https://github.com/${string}`
    | `https://docs.github.com/${string}`
    | `https://openrouter.ai/${string}`
    | `https://docs.signalpilot.ai/docs/${string}`
    | `https://docs.python.org/${string}`
    | `https://wandb.ai/${string}`
    | `https://portal.azure.com/${string}`
    | `https://opencode.ai/${string}`;
  children: React.ReactNode;
}) => {
  return (
    <a href={href} target="_blank" className="text-link hover:underline">
      {children}
    </a>
  );
};
