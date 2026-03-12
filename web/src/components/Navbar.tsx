import { NavLink } from 'react-router-dom'
import { signOut } from '../services/supabase'
import type { Session } from '@supabase/supabase-js'

interface NavbarProps {
  session: Session
}

export default function Navbar({ session }: NavbarProps) {
  return (
    <nav className="navbar">
      <div className="navbar-brand">
        <span className="logo">WatchLater</span>
      </div>

      <div className="navbar-links">
        <NavLink to="/" className={({ isActive }) => (isActive ? 'active' : '')}>
          Summarize
        </NavLink>
        <NavLink to="/history" className={({ isActive }) => (isActive ? 'active' : '')}>
          History
        </NavLink>
        <NavLink to="/knowledge-map" className={({ isActive }) => (isActive ? 'active' : '')}>
          Knowledge Map
        </NavLink>
        <NavLink to="/pricing" className={({ isActive }) => (isActive ? 'active' : '')}>
          Pricing
        </NavLink>
      </div>

      <div className="navbar-user">
        <span className="user-email">{session.user.email}</span>
        <button className="btn-text" onClick={() => signOut()}>
          Sign Out
        </button>
      </div>
    </nav>
  )
}
