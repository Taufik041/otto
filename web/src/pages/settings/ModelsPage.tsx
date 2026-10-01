import { useMutation } from '@tanstack/react-query'
import { Link } from 'react-router'
import { api, client } from '@/api'
import { messageOf } from '@/api/errors'
import { useModels } from '@/api/queries'
import { useMe } from '@/auth/auth'
import { ModelMenu } from '@/composer/ModelMenu'
import { initialModel } from '@/composer/models'
import { Card, Loading, Problem, SectionLabel } from './parts'

/** The model new chats start on (PATCH /me {default_model}). */
export function ModelsPage() {
  const me = useMe()
  const models = useModels()
  const save = useMutation({
    mutationFn: (id: string) => api.updateMe({ default_model: id }),
    onSuccess: (user) => client.setUser(user),
  })
  if (models.isPending) return <Loading />
  if (models.isError) return <Problem error={models.error} />
  const selected = save.isPending ? save.variables : initialModel(models.data, me.default_model)
  return (
    <>
      <div>
        <SectionLabel>Default model</SectionLabel>
        <Card className="p-1.5">
          <ModelMenu
            models={models.data.models}
            selected={selected ?? null}
            defaultId={models.data.default_model}
            rowPadding="10px 12px"
            autoFocus={false}
            onPick={(id) => id !== selected && save.mutate(id)}
          />
        </Card>
        {save.isError && <p role="alert" className="mx-1 mb-0 mt-2.5 text-sm text-bad">{messageOf(save.error)}</p>}
      </div>
      <p className="m-0 text-sm text-muted">
        Models run on Otto's keys. Your daily limit is shown under <Link to="/settings/usage">Usage</Link>.
      </p>
    </>
  )
}
