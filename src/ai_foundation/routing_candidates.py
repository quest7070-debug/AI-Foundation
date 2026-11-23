def merged_candidates(cloud=(),local=()):
    """Normalize cloud and local capacity into the one persisted routing policy.
    Guard privacy/authority remains outside this preference layer.
    """
    rows=[dict(x) for x in cloud]
    for c in local:
        rows.append({'binding':c.binding,'provider':c.provider,'tier':c.tier,'health':c.health,
                     'short_remaining':None,'long_remaining':None,'kind':'LOCAL',
                     'capabilities':tuple(c.capabilities)})
    return tuple(rows)
