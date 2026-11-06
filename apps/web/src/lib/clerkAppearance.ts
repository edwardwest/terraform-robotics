// Clerk components in the Terraform Robotics design system: monochrome, warm greys, flat cards.
export const clerkAppearance = {
  variables: {
    colorPrimary: "#ffffff",
    colorPrimaryForeground: "#000000",
    colorBackground: "#0e0f0b",
    colorForeground: "#ffffff",
    colorMutedForeground: "#a3a29a",
    colorMuted: "#1c1c15",
    colorInput: "#1c1c15",
    colorInputForeground: "#ffffff",
    colorBorder: "rgba(255,255,255,0.12)",
    colorNeutral: "#ffffff",
    colorRing: "rgba(255,255,255,0.5)",
    colorDanger: "#f2b8a2",
    colorShadow: "transparent",
    borderRadius: "10px",
    fontFamily: '"Helvetica Neue", Helvetica, Arial, sans-serif',
  },
  elements: {
    card: { boxShadow: "none", border: "1px solid rgba(255,255,255,0.12)", borderRadius: "12px" },
    cardBox: { boxShadow: "none" },
    headerTitle: { fontWeight: 700, letterSpacing: "-0.01em" },
    formButtonPrimary: { fontWeight: 700, boxShadow: "none" },
    socialButtonsBlockButton: { borderColor: "rgba(255,255,255,0.12)" },
    footer: { background: "transparent" },
    userButtonPopoverCard: { boxShadow: "none", border: "1px solid rgba(255,255,255,0.12)" },
  },
};
