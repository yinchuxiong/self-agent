import { CalendarOutlined } from "@ant-design/icons";
import { Empty, Typography } from "antd";
import PageHeader from "../components/PageHeader";

export default function TasksPage() {
  return (
    <div className="pageGrid">
      <PageHeader title="任务" subtitle="提醒、Cron、定时 Workflow 和执行历史" />
      <div className="emptyPanel">
        <CalendarOutlined />
        <Typography.Title level={4}>Scheduler 接口已预留</Typography.Title>
        <Typography.Text>后续会接 APScheduler，先完成提醒和 Workflow 定时触发。</Typography.Text>
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={false} />
      </div>
    </div>
  );
}

