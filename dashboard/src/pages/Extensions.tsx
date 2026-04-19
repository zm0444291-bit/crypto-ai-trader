const EXTENSIONS = [
  {
    name: 'FuturesMomentumTemplate',
    description: 'Momentum-based futures signal generation',
    milestone: 'Milestone 8',
  },
  {
    name: 'OrderBookImbalanceTemplate',
    description: 'Detect order book pressure shifts',
    milestone: 'Milestone 9',
  },
  {
    name: 'CrossExchangeArbitrageTemplate',
    description: 'Multi-exchange price discrepancy capture',
    milestone: 'Milestone 10',
  },
  {
    name: 'NewsSentimentTemplate',
    description: 'NLP-driven news sentiment signals',
    milestone: 'Milestone 11',
  },
  {
    name: 'OnchainFlowTemplate',
    description: 'On-chain fund flow analysis',
    milestone: 'Milestone 12',
  },
  {
    name: 'MLSignalTemplate',
    description: 'Machine learning price prediction',
    milestone: 'Milestone 13',
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
            <span className="ext-badge">Disabled — {ext.milestone}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
