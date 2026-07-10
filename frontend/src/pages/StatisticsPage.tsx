import { Card, Col, Row, Statistic, Table } from "antd";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import PageHeader from "../components/PageHeader";
import type { MetricOverview } from "../types";

export default function StatisticsPage() {
  const [metrics, setMetrics] = useState<MetricOverview>();

  useEffect(() => {
    void api.metrics().then(setMetrics);
  }, []);

  return (
    <div className="pageGrid">
      <PageHeader title="统计" subtitle="调用量、成功率、耗时、Token 与最近错误" />
      <Row gutter={[16, 16]}>
        <Col xs={24} md={8} xl={4}>
          <Card>
            <Statistic title="总调用" value={metrics?.total_calls ?? 0} />
          </Card>
        </Col>
        <Col xs={24} md={8} xl={4}>
          <Card>
            <Statistic title="成功率" value={(metrics?.success_rate ?? 0) * 100} suffix="%" precision={1} />
          </Card>
        </Col>
        <Col xs={24} md={8} xl={4}>
          <Card>
            <Statistic title="失败" value={metrics?.failed_calls ?? 0} />
          </Card>
        </Col>
        <Col xs={24} md={8} xl={4}>
          <Card>
            <Statistic title="平均耗时" value={metrics?.avg_latency_ms ?? 0} suffix="ms" />
          </Card>
        </Col>
        <Col xs={24} md={8} xl={4}>
          <Card>
            <Statistic title="P95" value={metrics?.p95_latency_ms ?? 0} suffix="ms" />
          </Card>
        </Col>
        <Col xs={24} md={8} xl={4}>
          <Card>
            <Statistic title="Token" value={metrics?.token_usage ?? 0} />
          </Card>
        </Col>
      </Row>
      <Table
        rowKey="id"
        dataSource={(metrics?.recent_errors as Record<string, unknown>[] | undefined) ?? []}
        columns={[
          { title: "Trace", dataIndex: "trace_id" },
          { title: "错误", dataIndex: "error_message" },
          { title: "时间", dataIndex: "created_at" }
        ]}
        locale={{ emptyText: "暂无错误" }}
      />
    </div>
  );
}

