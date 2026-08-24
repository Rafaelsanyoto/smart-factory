import { useState, useMemo, useRef } from 'react';
import { Send, SlashSquare } from 'lucide-react';
import { filterSlashCommands } from '../../lib/agentSlashCommands';

export default function AgentComposer({ onSend, disabled, placeholder }) {
  const [value, setValue] = useState('');
  const [highlightIdx, setHighlightIdx] = useState(0);
  const inputRef = useRef(null);

  const slashQuery = value.startsWith('/') ? value.slice(1) : null;
  const suggestions = useMemo(() => (slashQuery !== null ? filterSlashCommands(slashQuery) : []), [slashQuery]);
  const showSuggestions = slashQuery !== null && suggestions.length > 0;

  const pick = (cmd) => {
    setValue(cmd.insert);
    setHighlightIdx(0);
    inputRef.current?.focus();
  };

  const submit = (e) => {
    e.preventDefault();
    if (!value.trim() || disabled) return;
    onSend(value);
    setValue('');
    setHighlightIdx(0);
  };

  const onKeyDown = (e) => {
    if (!showSuggestions) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlightIdx((i) => (i + 1) % suggestions.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlightIdx((i) => (i - 1 + suggestions.length) % suggestions.length);
    } else if (e.key === 'Tab' || (e.key === 'Enter' && suggestions[highlightIdx])) {
      e.preventDefault();
      pick(suggestions[highlightIdx]);
    } else if (e.key === 'Escape') {
      setValue('');
    }
  };

  return (
    <div className="relative">
      {showSuggestions && (
        <div className="absolute bottom-full mb-2 left-0 right-0 bg-slate-950 border border-slate-700 rounded-lg shadow-2xl overflow-hidden max-h-56 overflow-y-auto z-20">
          {suggestions.map((c, idx) => (
            <button
              key={c.cmd}
              type="button"
              onClick={() => pick(c)}
              onMouseEnter={() => setHighlightIdx(idx)}
              className={`w-full text-left px-3 py-2 flex items-center gap-2.5 text-xs transition-colors ${
                idx === highlightIdx ? 'bg-slate-800 text-slate-100' : 'text-slate-400'
              }`}
            >
              <SlashSquare size={12} className="text-blue-400 shrink-0" />
              <span className="font-mono text-blue-300">{c.cmd}</span>
              <span className="text-slate-500 truncate">{c.label}</span>
            </button>
          ))}
        </div>
      )}
      <form onSubmit={submit} className="flex items-center gap-2">
        <input
          ref={inputRef}
          value={value}
          onChange={(e) => { setValue(e.target.value); setHighlightIdx(0); }}
          onKeyDown={onKeyDown}
          disabled={disabled}
          placeholder={placeholder}
          className="flex-1 bg-slate-950 border border-slate-700 text-slate-200 text-sm rounded-lg focus:ring-blue-500 focus:border-blue-500 p-3 disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={disabled || !value.trim()}
          className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:hover:bg-blue-600 text-white px-4 py-3 rounded-lg flex items-center gap-2 text-sm font-semibold transition-colors"
        >
          <Send size={16} />
        </button>
      </form>
    </div>
  );
}
