import { Inbox } from "lucide-react";
export function EmptyState({ title, copy }: { title: string; copy: string }) {
  return <div className="empty-state"><Inbox size={22} /><strong>{title}</strong><span>{copy}</span></div>;
}

