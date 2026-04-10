import type { LucideIcon } from "lucide-react";

export function EmptyState({
  icon: Icon,
  title,
  description,
}: {
  icon: LucideIcon;
  title: string;
  description?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="w-14 h-14 rounded-full bg-sand flex items-center justify-center mb-4">
        <Icon size={24} className="text-mist" />
      </div>
      <h3 className="text-sm font-semibold text-navy">{title}</h3>
      {description && (
        <p className="text-xs text-mist mt-1 max-w-xs">{description}</p>
      )}
    </div>
  );
}
