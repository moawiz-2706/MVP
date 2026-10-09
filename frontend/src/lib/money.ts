export function minorToDollars(minor: number): string {
  return (minor / 100).toFixed(2);
}

export function dollarsToMinor(value: string): number {
  const normalized = value.trim();
  if (!/^\d+(?:\.\d{0,2})?$/.test(normalized)) {
    throw new Error("Enter a valid dollar amount with up to two decimal places");
  }

  const [whole, fraction = ""] = normalized.split(".");
  const minor = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  if (!Number.isSafeInteger(minor)) {
    throw new Error("Dollar amount is too large");
  }
  return minor;
}
