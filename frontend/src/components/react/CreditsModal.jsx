import { Heart } from "lucide-react";
import { Modal } from "./ui/Modal.jsx";
import { CREDITS } from "@/data/credits.js";

function initials(name = "") {
  return (
    name
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((p) => p[0])
      .join("")
      .toUpperCase() || "?"
  );
}

// Deterministic soft gradient per person so avatars feel distinct but on-brand.
const AVATAR_GRADIENTS = [
  "from-orange-400 to-pink-500",
  "from-pink-500 to-violet-500",
  "from-violet-500 to-blue-500",
  "from-blue-500 to-cyan-500",
  "from-emerald-500 to-teal-500",
  "from-amber-500 to-orange-500",
  "from-fuchsia-500 to-purple-500",
  "from-rose-500 to-red-500",
  "from-sky-500 to-indigo-500",
  "from-teal-500 to-green-500",
];

/** "Made with ♥ by Adobe" — team credits dialog. */
export function CreditsModal({ open, onClose }) {
  return (
    <Modal open={open} onClose={onClose} size="md">
      <div className="text-center">
        <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl brand-gradient text-white">
          <Heart size={22} aria-hidden="true" fill="currentColor" />
        </span>
        <h2 className="mt-4 text-xl font-semibold text-fg">
          Made with ♥ by Adobe Team
        </h2>
        <p className="mt-1 text-sm text-muted">
          OmniBrand Studio was crafted by this team.
        </p>
      </div>

      <ul className="mt-6 grid gap-2 sm:grid-cols-2">
        {CREDITS.map((name, i) => (
          <li
            key={name}
            className="flex items-center gap-3 rounded-xl border border-border bg-surface-2 px-3 py-2"
          >
            <span
              className={`grid h-9 w-9 shrink-0 place-items-center rounded-full bg-gradient-to-br ${
                AVATAR_GRADIENTS[i % AVATAR_GRADIENTS.length]
              } text-xs font-semibold text-white`}
              aria-hidden="true"
            >
              {initials(name)}
            </span>
            <span className="truncate text-sm font-medium text-fg">{name}</span>
          </li>
        ))}
      </ul>

      <p className="mt-6 text-center text-xs text-faint">
        © {new Date().getFullYear()} Adobe · OmniBrand Studio
      </p>
    </Modal>
  );
}
