/* Satisfy the steg patch inside the bundled libjpeg when building helpers. */
short
steg_use_bit (unsigned short temp)
{
	return (short) temp;
}
