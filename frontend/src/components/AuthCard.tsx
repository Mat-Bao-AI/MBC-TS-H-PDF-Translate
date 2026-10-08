import type { ReactNode } from 'react';
import { Box, Card, FlexBox, Text } from '@codecademy/gamut';
import { t } from '../i18n/t';

type Props = { title: string; children: ReactNode; footer?: ReactNode; maxWidth?: string; step?: string };

export function AuthCard({ title, children, footer, maxWidth = '420px', step }: Props) {
  return (
    <FlexBox bg="background-selected" minHeight="100vh" justifyContent="center" alignItems="center" px={16} py={32}>
      <Box width="100%" maxWidth={maxWidth}>
        <Text as="p" fontSize={20} fontWeight="title" textAlign="center" mb={16}>
          {t('app.name')}
        </Text>
        <Card p={32}>
          {step && (
            <Text as="p" fontSize={14} color="text-secondary" mb={8}>
              {step}
            </Text>
          )}
          <Text as="h1" variant="title-md" mb={24}>
            {title}
          </Text>
          {children}
        </Card>
        {footer && (
          <FlexBox justifyContent="center" alignItems="center" gap={8} mt={16} flexWrap="wrap">
            {footer}
          </FlexBox>
        )}
      </Box>
    </FlexBox>
  );
}
