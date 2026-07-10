import { Tag } from "antd";
import type { PermissionLevel } from "../types";

const colorByLevel: Record<PermissionLevel, string> = {
  read: "blue",
  write: "green",
  execute: "gold",
  external_publish: "purple",
  dangerous: "red"
};

export function PermissionTag({ level }: { level: PermissionLevel }) {
  return <Tag color={colorByLevel[level]}>{level}</Tag>;
}

export function EnabledTag({ enabled }: { enabled: boolean }) {
  return <Tag color={enabled ? "success" : "default"}>{enabled ? "启用" : "禁用"}</Tag>;
}

