// Equal-opportunity answers and degrees for Settings (#142). The values are what screening_defaults stores; the
// option patterns in jobs/apply/eeo_patterns.json use the same values (web/tests/eeo.test.mjs checks).
// 'prefer_not' is never stored: it and a missing value both make remote fill pick the form's decline option.
export const PREFER_NOT = 'prefer_not';

const preferNot = { value: PREFER_NOT, label: 'Prefer not to say' };

export const EEO_FIELDS = {
  gender: [preferNot, { value: 'woman', label: 'Woman' }, { value: 'man', label: 'Man' }, { value: 'non_binary', label: 'Non-binary' }],
  race: [
    preferNot,
    { value: 'asian', label: 'Asian' },
    { value: 'black', label: 'Black or African American' },
    { value: 'hispanic_latino', label: 'Hispanic or Latino' },
    { value: 'native_american', label: 'Native American or Alaska Native' },
    { value: 'pacific_islander', label: 'Native Hawaiian or Pacific Islander' },
    { value: 'white', label: 'White' },
    { value: 'two_or_more', label: 'Two or more races' }
  ],
  veteran: [preferNot, { value: 'not_veteran', label: 'I am not a protected veteran' }, { value: 'protected_veteran', label: 'I am a protected veteran' }],
  disability: [preferNot, { value: 'no', label: 'No, I don’t have a disability' }, { value: 'yes', label: 'Yes, I have a disability' }]
} satisfies Record<string, { value: string; label: string }[]>;

export type EeoField = keyof typeof EEO_FIELDS;
export type EeoAnswers = Partial<Record<EeoField, string>>;

export const DEGREES: { value: string; label: string }[] = [
  { value: 'bachelors', label: 'Bachelor’s' },
  { value: 'masters', label: 'Master’s' },
  { value: 'phd', label: 'PhD' },
  { value: 'associates', label: 'Associate’s' },
  { value: 'high_school', label: 'High school' },
  { value: 'other', label: 'Other' }
];
