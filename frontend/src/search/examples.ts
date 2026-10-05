// One example per question class (CLAUDE.md §1 coverage matrix), so the chips also show what the
// system covers. Each is an eval question expected to return `ok`, copied verbatim; a test keeps
// them in sync with eval/questions.json.
export interface Example {
  evalId: string
  questionClass: string
  label: string // the chip's class tag
  query: string
}

export const EXAMPLES: readonly Example[] = [
  {
    evalId: 'tt_drug_since_2015',
    questionClass: 'time_trend',
    label: 'Time trend',
    query: 'How has the number of trials for pembrolizumab changed per year since 2015?',
  },
  {
    evalId: 'dist_phase_condition',
    questionClass: 'distribution',
    label: 'Distribution',
    query: 'How are breast cancer trials distributed across phases?',
  },
  {
    evalId: 'cmp_phase_two_drugs',
    questionClass: 'comparison',
    label: 'Comparison',
    query: 'Compare phases for trials involving pembrolizumab vs nivolumab.',
  },
  {
    evalId: 'geo_recruiting_condition',
    questionClass: 'geographic',
    label: 'Geographic',
    query: 'Which countries have the most recruiting trials for cystic fibrosis?',
  },
  {
    evalId: 'net_drug_drug_condition',
    questionClass: 'network',
    label: 'Network',
    query: 'Which drugs frequently co-occur in combination studies for melanoma?',
  },
  {
    evalId: 'num_enrollment_histogram',
    questionClass: 'numeric',
    label: 'Enrollment',
    query: 'What is the distribution of enrollment sizes for adalimumab trials?',
  },
]
