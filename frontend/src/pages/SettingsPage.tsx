import { Descriptions } from "antd";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import PageHeader from "../components/PageHeader";

export default function SettingsPage() {
  const [settings, setSettings] = useState<Record<string, unknown>>({});

  useEffect(() => {
    void api.settings().then(setSettings);
  }, []);

  return (
    <div className="pageGrid">
      <PageHeader title="设置" subtitle="LLM、数据库、向量库、路径白名单和日志保留策略" />
      <Descriptions bordered column={1}>
        {Object.entries(settings).map(([key, value]) => (
          <Descriptions.Item key={key} label={key}>
            {String(value)}
          </Descriptions.Item>
        ))}
      </Descriptions>
    </div>
  );
}

