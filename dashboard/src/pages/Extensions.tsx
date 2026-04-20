const EXTENSIONS = [
  {
    name: 'FuturesMomentumTemplate',
    description: '基于动量的期货信号生成',
    milestone: '里程碑 8',
  },
  {
    name: 'OrderBookImbalanceTemplate',
    description: '检测订单簿压力变化',
    milestone: '里程碑 9',
  },
  {
    name: 'CrossExchangeArbitrageTemplate',
    description: '捕捉多交易所价差机会',
    milestone: '里程碑 10',
  },
  {
    name: 'NewsSentimentTemplate',
    description: '基于 NLP 的新闻情绪信号',
    milestone: '里程碑 11',
  },
  {
    name: 'OnchainFlowTemplate',
    description: '链上资金流分析',
    milestone: '里程碑 12',
  },
  {
    name: 'MLSignalTemplate',
    description: '机器学习价格预测',
    milestone: '里程碑 13',
  },
];

export default function Extensions() {
  return (
    <div className="page">
      <div className="extensions-grid">
        {EXTENSIONS.map((ext) => (
          <div key={ext.name} className="extension-card">
            <div className="ext-name">{ext.name}</div>
            <div className="ext-desc">{ext.description}</div>
            <span className="ext-badge">未启用 — {ext.milestone}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
