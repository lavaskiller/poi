import type { ButtonHTMLAttributes, ReactNode } from "react";
import styles from "./Button.module.css";

type ButtonKind = "primary" | "secondary" | "ghost";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  kind?: ButtonKind;
  loading?: boolean;
  children: ReactNode;
}

export default function Button({
  kind = "primary",
  loading = false,
  disabled,
  children,
  className,
  ...rest
}: ButtonProps) {
  return (
    <button
      type="button"
      className={[styles.btn, styles[kind], className].filter(Boolean).join(" ")}
      disabled={disabled || loading}
      data-loading={loading || undefined}
      {...rest}
    >
      {loading && <span className={styles.spinner} aria-hidden />}
      <span>{loading ? "Running…" : children}</span>
    </button>
  );
}
