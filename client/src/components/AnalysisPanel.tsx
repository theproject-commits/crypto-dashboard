import type { AnalysisHorizon, DetailTab } from '../analysis-types';

interface AnalysisPanelProps {
  activeDetailTab: DetailTab | null;
  analysisHorizon: AnalysisHorizon;
  onTabChange: (tab: DetailTab) => void;
  onHorizonChange: (horizon: AnalysisHorizon) => void;
}

export function AnalysisPanel({ activeDetailTab, analysisHorizon, onTabChange, onHorizonChange }: AnalysisPanelProps) {
  return (
    <>
      <h3>Análise</h3>
      <div className="tab-row">
        <button
          className={`tab-button ${activeDetailTab === 'predicao' ? 'active' : ''}`}
          onClick={() => onTabChange('predicao')}
        >
          Features Técnicas
        </button>
        <button
          className={`tab-button ${activeDetailTab === 'estado' ? 'active' : ''}`}
          onClick={() => onTabChange('estado')}
        >
          Estado
        </button>
        <button
          className={`tab-button ${activeDetailTab === 'composite' ? 'active' : ''}`}
          onClick={() => onTabChange('composite')}
        >
          Composite
        </button>
      </div>
      <div className="horizon-row">
        {(['24h', '7d', '30d'] as AnalysisHorizon[]).map((horizon) => (
          <button
            key={horizon}
            className={`horizon-button ${analysisHorizon === horizon ? 'active' : ''}`}
            onClick={() => onHorizonChange(horizon)}
          >
            {horizon}
          </button>
        ))}
      </div>
      <p className="metric">Selecione uma aba e o horizonte para abrir os detalhes no painel abaixo.</p>
    </>
  );
}
