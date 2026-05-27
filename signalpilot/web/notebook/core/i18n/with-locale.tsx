import { useLocale } from "react-aria";

export const WithLocale = ({
  children,
}: {
  children: (locale: string) => React.ReactNode;
}) => {
  const { locale } = useLocale();
  return children(locale);
};
