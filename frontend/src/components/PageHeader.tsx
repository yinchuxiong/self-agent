import { Space, Typography } from "antd";
import type { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  subtitle: string;
  actions?: ReactNode;
}

export default function PageHeader({ title, subtitle, actions }: PageHeaderProps) {
  return (
    <div className="pageHeader">
      <div>
        <Typography.Title level={2}>{title}</Typography.Title>
        <Typography.Text>{subtitle}</Typography.Text>
      </div>
      {actions ? <Space>{actions}</Space> : null}
    </div>
  );
}

