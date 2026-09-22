---
name: "Remote Job Agent — Minimalist Modern Design System"
author: "Frontend & UI/UX Design System"
version: "2.0.0"
source: "Vercel & Stripe Minimalist Precision with Linear Workflow (awesome-design-md standard)"
tokens:
  dark_theme:
    background:
      canvas: "#0c0d0e"            # Neutral Zinc (replaces heavy murky blue)
      surface: "#141518"           # Clean dark slate card surface
      surface_glass: "rgba(20, 21, 24, 0.88)"
      surface_elevated: "#1c1d22"  # Elevated containers & inputs
      surface_hover: "#24262d"     # Active hover state
      card: "#141518"
    borders:
      subtle: "rgba(255, 255, 255, 0.12)" # Crisp high-contrast hairline
      active: "#3b82f6"           # Electric Blue focus
      focus: "#3b82f6"
      glass: "rgba(255, 255, 255, 0.16)"
    text:
      primary: "#ffffff"          # 100% crisp white for headings & values
      secondary: "#cbd5e1"        # High-legibility silver-gray (WCAG AAA)
      muted: "#94a3b8"            # Clear, readable metadata (WCAG AA)
      inverse: "#0c0d0e"
    accents:
      primary: "#3b82f6"          # Modern Minimalist Royal Blue
      primary_hover: "#2563eb"
      success: "#10b981"          # Crisp Emerald for Top Matches (>=85%)
      warning: "#f59e0b"          # Amber for Good Matches (70-84%)
      danger: "#ef4444"           # Red for Rejections & Auto-Submit safety
      cyan: "#0ea5e9"             # Cyan for Salaries & Tags

  light_theme:
    background:
      canvas: "#f8fafc"           # Clean airy slate-50
      surface: "#ffffff"          # Crisp white card surface
      surface_glass: "rgba(255, 255, 255, 0.92)"
      surface_elevated: "#f1f5f9" # Light gray inputs
      surface_hover: "#e2e8f0"
      card: "#ffffff"
    borders:
      subtle: "#e2e8f0"
      active: "#3b82f6"
      focus: "#3b82f6"
      glass: "rgba(0, 0, 0, 0.08)"
    text:
      primary: "#0f172a"          # Deep slate-900
      secondary: "#334155"        # Slate-700
      muted: "#64748b"            # Slate-500
      inverse: "#ffffff"
    accents:
      primary: "#2563eb"
      primary_hover: "#1d4ed8"
      success: "#059669"
      warning: "#d97706"
      danger: "#dc2626"
      cyan: "#0284c7"

  typography:
    font_family:
      sans: "'Plus Jakarta Sans', 'Inter', system-ui, -apple-system, sans-serif"
      mono: "'JetBrains Mono', 'Fira Code', monospace"
    font_weights:
      normal: 400
      medium: 500
      semibold: 600
      bold: 700
  spacing:
    xs: "4px"
    sm: "8px"
    md: "16px"
    lg: "24px"
    xl: "32px"
  border_radius:
    sm: "6px"
    md: "10px"
    lg: "14px"
    pill: "9999px"
  shadows:
    card: "0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px -1px rgba(0, 0, 0, 0.1)"
    card_elevated: "0 4px 16px -2px rgba(0, 0, 0, 0.25)"
---

# DESIGN.md — Remote Job Agent Command Center (v2.0)

## 1. Minimalist Modern Philosophy & Visual Principles

This design system upgrades the interface from a heavy dark aesthetic to a **precision-engineered Minimalist Modern workspace** inspired by **Vercel, Stripe, and Linear**:

1. **High-Contrast Legibility First (WCAG AAA Compliant)**:
   - Primary text is pure crisp white (`#FFFFFF`) in dark mode and deep slate (`#0F172A`) in light mode.
   - Secondary text is bright silver-slate (`#CBD5E1`), strictly eliminating murky, low-contrast grays.
   - Metadata and tags remain sharp and easily readable at any distance.
2. **Neutral Precision Palette**:
   - Replaced heavy navy/purple background tints with refined **Neutral Zinc & Slate** (`#0C0D0E` canvas, `#141518` cards).
   - Razor-sharp 1px borders (`rgba(255, 255, 255, 0.12)`) create distinct, well-defined card boundaries without blurry glow effects.
3. **Dual-Theme Minimalist Toggle**:
   - One-click instant switching between **Minimalist Modern Dark** and **Clean Enterprise Light** mode.
4. **Focused Information Density (Linear Master-Detail Drawer)**:
   - Clean, uncluttered layout with deliberate whitespace.
   - Slide-over drawer keeps the user's focus on job evaluation without leaving the list.

---

## 2. Core Components & Visual Rules

- **Bento KPI Cards**: Clean white metric values with compact progress tracks and high-contrast labels.
- **Match Score Indicator**:
  - `≥ 85%`: Crisp Emerald (`#10B981`) with clear high-contrast border and badge.
  - `70% - 84%`: Warm Amber (`#F59E0B`) with readable text.
  - `< 70%`: Slate Gray (`#94A3B8`).
- **Job Cards**:
  - Crisp white job titles with bright company names.
  - High-contrast pill tags with distinct backgrounds and readable text.
  - Clean action buttons with subtle border transitions.
- **High-Density Spreadsheet View**:
  - Crisp table rows with subtle dividers, clear text alignment, and sticky headers.
- **Slide-Over Inspection Drawer**:
  - Slides from right with high-contrast text, clear skills breakdown (Emerald for matched, Rose for missing), and full description.
- **CV Studio & Auto-Apply Safety**:
  - Clean dropzone with high-contrast border.
  - Clear safety indicators (`Fill & Review` in Emerald vs `Live Auto-Submit` in Red).
