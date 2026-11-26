/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef TAS25XX_BIN_VALIDATE_H
#define TAS25XX_BIN_VALIDATE_H

/* Validate the entire selected image before the legacy parser creates pointers
 * into it. No allocations, I/O or unaligned loads are performed here. */
struct tas_bin_cursor {
	const u8 *p;
	size_t n;
};

static bool tas_bin_take(struct tas_bin_cursor *c, size_t n,
			 const u8 **out)
{
	if (n > c->n)
		return false;
	if (out)
		*out = c->p;
	c->p += n;
	c->n -= n;
	return true;
}

static u32 tas_bin_le32(const u8 *p)
{
	return (u32)p[0] | (u32)p[1] << 8 | (u32)p[2] << 16 |
		(u32)p[3] << 24;
}

static bool tas_bin_u32(struct tas_bin_cursor *c, u32 *v)
{
	const u8 *p;

	if (!tas_bin_take(c, 4, &p))
		return false;
	*v = tas_bin_le32(p);
	return true;
}

static bool tas_bin_sub(struct tas_bin_cursor *c, struct tas_bin_cursor *s)
{
	u32 n;

	if (!tas_bin_u32(c, &n) || n > c->n)
		return false;
	s->p = c->p;
	s->n = n;
	return tas_bin_take(c, n, NULL);
}

static bool tas_bin_name(struct tas_bin_cursor *c)
{
	const u8 *p;

	return tas_bin_take(c, 64, &p) && memchr(p, 0, 64);
}

static bool tas_bin_commands(struct tas_bin_cursor c, bool read_check)
{
	const u8 *p;
	u32 n;

	while (c.n) {
		if (!tas_bin_take(&c, 1, &p))
			return false;
		switch (*p) {
		case 0: /* single register */
			if (!tas_bin_take(&c, 5, NULL))
				return false;
			break;
		case 1: /* burst */
			if (read_check || !tas_bin_take(&c, 4, NULL) ||
			    !tas_bin_u32(&c, &n) || !n ||
			    !tas_bin_take(&c, n, NULL))
				return false;
			break;
		case 2: /* masked register */
			if (!tas_bin_take(&c, 6, NULL))
				return false;
			break;
		case 3: /* delay in ms; keep multiplication representable */
			if (read_check || !tas_bin_u32(&c, &n) || n > 10000)
				return false;
			break;
		default:
			return false;
		}
	}
	return true;
}

static bool tas_bin_cmd_block(struct tas_bin_cursor *c)
{
	struct tas_bin_cursor s;

	return tas_bin_sub(c, &s) && tas_bin_commands(s, false);
}

static bool tas_bin_formats(struct tas_bin_cursor c, size_t name_len)
{
	u32 n;

	if (!tas_bin_u32(&c, &n) || !n || n > c.n / (name_len + 4))
		return false;
	while (n--)
		if (!tas_bin_take(&c, name_len, NULL) || !tas_bin_cmd_block(&c))
			return false;
	return !c.n;
}

static bool tas_bin_controls(struct tas_bin_cursor c, u32 version, u32 channels)
{
	u32 n, count, kind, def, min, max, step;
	const u8 *p;

	if (!tas_bin_u32(&c, &n) || n > c.n / 71)
		return false;
	while (n--) {
		if (!tas_bin_take(&c, 1, &p) || *p > 1)
			return false;
		kind = *p;
		if (!tas_bin_name(&c) || !tas_bin_take(&c, 1, &p) || *p >= channels)
			return false;
		if (!kind) {
			if (!tas_bin_take(&c, 4, NULL) || !tas_bin_take(&c, 1, &p) || *p > 2)
				return false;
			kind = *p;
			if ((kind == 2 && !tas_bin_take(&c, 4, NULL)) ||
			    !tas_bin_u32(&c, &min) || !tas_bin_u32(&c, &max) ||
			    !tas_bin_u32(&c, &step) || !tas_bin_u32(&c, &def) ||
			    (version > 6 && !tas_bin_take(&c, 4, NULL)) ||
			    !tas_bin_u32(&c, &count) || !count || def >= count ||
			    count > c.n / (kind == 1 ? 4 : 1))
				return false;
			if (!tas_bin_take(&c, (size_t)count * (kind == 1 ? 4 : 1), NULL))
				return false;
		} else {
			if (!tas_bin_take(&c, 1, &p))
				return false;
			def = *p;
			if ((version > 6 && !tas_bin_take(&c, 4, NULL)) ||
			    !tas_bin_u32(&c, &count) || !count || def >= count ||
			    count > c.n / 68)
				return false;
			while (count--)
				if (!tas_bin_name(&c) || !tas_bin_cmd_block(&c))
					return false;
		}
	}
	return !c.n;
}

static bool tas_bin_validate(const u8 *data, size_t len, u32 channels)
{
	struct tas_bin_cursor c = { data, len }, s, t;
	const u8 *tag, *p;
	u32 version = 0, seen[2] = { 0 }, n, i, profile_count = 0;
	int ch = -1;
	bool header = false, controls = false;

	if (!channels || channels > 2 || len > 16 * 1024 * 1024)
		return false;
	while (c.n) {
		if (!tas_bin_take(&c, 5, &tag) || !tas_bin_sub(&c, &s))
			return false;
		if (!memcmp(tag, "HEADR", 5)) {
			if (header || ch != -1 || !tas_bin_take(&s, 118, &p) || s.n)
				return false;
			version = tas_bin_le32(p);
			if (!version || version > 7 || !memchr(p + 4, 0, 64) ||
			    tas_bin_le32(p + 76) != channels)
				return false;
			for (i = 0; i < 8; i++)
				if (p[90 + i] >= (i == 1 || i == 2 ? 4 : 3))
					return false;
			header = true;
			continue;
		}
		if (!header)
			return false;
		if (!memcmp(tag, "INITP", 5)) {
			if (++ch >= channels || !tas_bin_commands(s, false))
				return false;
			seen[ch] = 1;
		} else if (!memcmp(tag, "KCNTR", 5)) {
			if (controls || !tas_bin_controls(s, version, channels))
				return false;
			controls = true;
		} else if (!memcmp(tag, "ALGOP", 5)) {
			/* Legacy AFE algorithm transport is not built for this target. */
		} else {
			if (ch < 0)
				return false;
			if (!memcmp(tag, "HWPRM", 5)) {
				if (seen[ch] & 2 || !tas_bin_u32(&s, &n) || n != 26)
					return false;
				for (i = 0; i < 26; i++)
					if (!tas_bin_cmd_block(&s))
						return false;
				seen[ch] |= 2;
			} else if (!memcmp(tag, "PROFP", 5)) {
				if (seen[ch] & 4 || !tas_bin_take(&s, 1, &p) || !*p)
					return false;
				n = *p;
				if (ch && n != profile_count)
					return false;
				profile_count = n;
				while (n--) {
					if (!tas_bin_name(&s) || !tas_bin_take(&s, 4, NULL))
						return false;
					for (i = 0; i < 4; i++)
						if (!tas_bin_cmd_block(&s))
							return false;
				}
				seen[ch] |= 4;
			} else if (!memcmp(tag, "INTRP", 5)) {
				if (seen[ch] & 8 || !tas_bin_take(&s, 1, &p))
					return false;
				n = *p;
				for (i = 0; i < 3; i++)
					if (!tas_bin_cmd_block(&s))
						return false;
				if (!tas_bin_take(&s, (size_t)n * 92 + 24, NULL))
					return false;
				seen[ch] |= 8;
			} else if (!memcmp(tag, "BLKOP", 5)) {
				u32 required = 0;

				if (seen[ch] & 16 || !tas_bin_u32(&s, &n) || n > s.n / 9)
					return false;
				while (n--) {
					if (!tas_bin_take(&s, 5, &p) || !tas_bin_sub(&s, &t))
						return false;
					if (!memcmp(p, "RXFMT", 5)) {
						if (required & 1 || !tas_bin_formats(t, 5))
							return false;
						required |= 1;
					} else if (!memcmp(p, "TXFMT", 5)) {
						if (required & 2 || !tas_bin_formats(t, 14))
							return false;
						required |= 2;
					} else if (!memcmp(p, "DFREG", 5)) {
						/* OS4.0.7 carries an empty optional debug-register block. */
						if (t.n)
							return false;
					} else if (!memcmp(p, "PWRCK", 5)) {
						if (!tas_bin_commands(t, true))
							return false;
					} else if (!memcmp(p, "SWRST", 5) || !memcmp(p, "MUTE0", 5) ||
						   !memcmp(p, "CLINI", 5) || !memcmp(p, "CLDIN", 5)) {
						if (!tas_bin_commands(t, false))
							return false;
					} else {
						return false;
					}
				}
				if (required != 3)
					return false;
				seen[ch] |= 16;
			} else {
				return false;
			}
			if (s.n)
				return false;
		}
	}
	if (!header || !controls || ch + 1 != channels)
		return false;
	for (i = 0; i < channels; i++)
		if (seen[i] != 31)
			return false;
	return true;
}

/* Select a revision without trusting the metadata's offsets or lengths. */
static bool tas_bin_select(const u8 *data, size_t len, u32 revision,
			   const u8 **selected, size_t *selected_len)
{
	struct tas_bin_cursor c = { data, len }, images;
	const u8 *p;
	u32 n, i, size;
	bool found = false;

	if (len < 5 || len > 16 * 1024 * 1024)
		return false;
	if (memcmp(data, "MDATA", 5)) {
		*selected = data;
		*selected_len = len;
		return true;
	}
	if (!tas_bin_take(&c, 5, NULL) || !tas_bin_u32(&c, &n) ||
	    !n || n > c.n / 20)
		return false;
	images.p = c.p + (size_t)n * 20;
	images.n = c.n - (size_t)n * 20;
	for (i = 0; i < n; i++) {
		if (!tas_bin_take(&c, 20, &p))
			return false;
		size = tas_bin_le32(p + 4);
		if (!size || size > images.n)
			return false;
		if (tas_bin_le32(p) == revision) {
			if (found)
				return false;
			*selected = images.p;
			*selected_len = size;
			found = true;
		}
		if (!tas_bin_take(&images, size, NULL))
			return false;
	}
	return found && !images.n;
}
#endif
