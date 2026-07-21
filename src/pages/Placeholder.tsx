export default function Placeholder({ title }: { title: string }) {
  return (
    <main
      style={{
        flex: "1 0 0",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 8,
        color: "var(--text-tertiary)",
      }}
    >
      <p className="sectionLabel">{title}</p>
      <p style={{ fontSize: 14, color: "var(--text-secondary)" }}>
        This screen is next in the redesign build-out.
      </p>
    </main>
  );
}
