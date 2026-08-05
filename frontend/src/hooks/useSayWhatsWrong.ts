'use client';

import { useMutation } from '@tanstack/react-query';
import { apiClient } from '@/src/lib/api';

/**
 * File what is wrong with the list, from the list.
 *
 * Two words is a real answer — "wrong person", "opens blank". The row that is
 * open goes with it, so the words do not have to carry the context too.
 */
export function useSayWhatsWrong() {
  return useMutation({
    mutationFn: (body: { text: string; subject?: string }) => apiClient.sayWhatsWrong(body),
  });
}
