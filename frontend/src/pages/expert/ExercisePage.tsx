import { Link, useParams } from "react-router-dom";
import { api } from "../../api";
import ErrorNotice from "../../components/ErrorNotice";
import VerifyPanel from "../../components/VerifyPanel";
import { useLoad } from "../../hooks";

export default function ExercisePage() {
  const { id = "" } = useParams();
  const { data, error, reload } = useLoad(() => api.knowledge(id), [id]);
  if (error) return <ErrorNotice error={error} onReload={reload} />;
  if (!data)
    return (
      <p className="busy" role="status">
        Loading…
      </p>
    );
  return (
    <div className="stack narrow">
      <Link className="small" to={`/expert/findings/${data.finding_id}`}>
        ← Back to the finding
      </Link>
      <VerifyPanel versionId={data.id} versionNo={data.version_no} expectedRole="expert" />
    </div>
  );
}
