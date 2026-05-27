export const CssVariables: React.FC<{
  variables: Record<`--sp-${string}`, string>;
  children: React.ReactNode;
}> = ({ variables, children }) => {
  return (
    <div className="contents" style={variables}>
      {children}
    </div>
  );
};
