import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Line } from 'recharts'

export interface AnnualChartPoint {
  mois: string
  entrees: number
  sorties: number
  solde: number
}

// Isolé dans son propre chunk : recharts est une librairie lourde, elle ne doit
// être chargée que lorsque l'onglet "Synthèse annuelle" est réellement affiché
// (voir le lazy() + Suspense dans Rapports.tsx).
export default function AnnualBarChart({ data }: { data: AnnualChartPoint[] }) {
  return (
    <ResponsiveContainer width="100%" height={360} minWidth={0} minHeight={280}>
      <BarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f0f0f0" />
        <XAxis dataKey="mois" axisLine={false} tickLine={false} />
        <YAxis axisLine={false} tickLine={false} />
        <Tooltip
          contentStyle={{ borderRadius: '8px', border: '1px solid #e2e8f0' }}
          cursor={{ fill: '#f8fafc' }}
        />
        <Legend verticalAlign="top" align="right" height={36} />
        <Bar dataKey="entrees" name="Entrées" fill="#0b5d43" radius={[3, 3, 0, 0]} />
        <Bar dataKey="sorties" name="Sorties" fill="#00A09D" radius={[3, 3, 0, 0]} />
        <Line type="monotone" dataKey="solde" name="Solde net" stroke="#f59e0b" strokeWidth={2} />
      </BarChart>
    </ResponsiveContainer>
  )
}
