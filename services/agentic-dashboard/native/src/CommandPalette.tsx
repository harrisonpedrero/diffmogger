import { Command, Loader2, Search, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { PaletteCommand, PaletteCommandId } from "./commandPaletteModel";
import { filterPaletteCommands } from "./commandPaletteModel";

export function CommandPalette(props: {
  commands: PaletteCommand[];
  busyCommandId?: PaletteCommandId | "";
  message?: string;
  error?: string;
  onClose: () => void;
  onExecute: (command: PaletteCommand) => void;
}) {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const filtered = useMemo(() => filterPaletteCommands(props.commands, query), [props.commands, query]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  function move(delta: number) {
    if (!filtered.length) return;
    setActiveIndex((current) => {
      const next = current + delta;
      if (next < 0) return filtered.length - 1;
      if (next >= filtered.length) return 0;
      return next;
    });
  }

  function execute(command: PaletteCommand | undefined) {
    if (!command || command.disabledReason || props.busyCommandId) return;
    props.onExecute(command);
  }

  return (
    <div className="palette-backdrop" role="presentation" onMouseDown={props.onClose}>
      <div
        className="command-palette"
        role="dialog"
        aria-label="Command palette"
        aria-modal="true"
        onMouseDown={(event) => event.stopPropagation()}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            props.onClose();
          }
          if (event.key === "ArrowDown") {
            event.preventDefault();
            move(1);
          }
          if (event.key === "ArrowUp") {
            event.preventDefault();
            move(-1);
          }
          if (event.key === "Enter") {
            event.preventDefault();
            execute(filtered[activeIndex]);
          }
        }}
      >
        <div className="palette-search">
          <Search size={17} />
          <input
            ref={inputRef}
            aria-label="Search commands"
            aria-controls="command-palette-results"
            aria-activedescendant={filtered[activeIndex] ? `palette-command-${filtered[activeIndex].id}` : undefined}
            placeholder="Search commands"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <kbd>⌘K</kbd>
          <button aria-label="Close command palette" title="Close command palette" onClick={props.onClose}>
            <X size={16} />
          </button>
        </div>

        {props.error && <div className="palette-status error" role="status" aria-live="polite">{props.error}</div>}
        {props.message && <div className="palette-status" role="status" aria-live="polite">{props.message}</div>}

        <div className="palette-command-list" id="command-palette-results" role="listbox" aria-label="Commands">
          {filtered.length ? (
            filtered.map((command, index) => {
              const disabled = Boolean(command.disabledReason || props.busyCommandId);
              const busy = props.busyCommandId === command.id;
              return (
                <button
                  aria-selected={index === activeIndex}
                  className={`${index === activeIndex ? "active" : ""} ${disabled ? "disabled" : ""}`}
                  disabled={disabled}
                  id={`palette-command-${command.id}`}
                  key={command.id}
                  role="option"
                  title={command.disabledReason}
                  onClick={() => execute(command)}
                  onMouseEnter={() => setActiveIndex(index)}
                >
                  <span className="palette-command-icon">
                    {busy ? <Loader2 size={16} className="spin" /> : <Command size={16} />}
                  </span>
                  <span>
                    <strong>{command.title}</strong>
                    <small>{command.disabledReason || command.description}</small>
                  </span>
                  <em>{command.dangerous ? "confirm" : command.section}</em>
                </button>
              );
            })
          ) : (
            <div className="palette-empty">No matching commands.</div>
          )}
        </div>
      </div>
    </div>
  );
}
