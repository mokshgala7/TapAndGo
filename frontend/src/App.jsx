import AppRoutes from './routes/AppRoutes.jsx'
import ScrollCar from './components/Common/ScrollCar.jsx'

// The site opens straight on the page; the intro video no longer plays on load or reload.
function App() {
  return (
    <>
      <AppRoutes />
      <ScrollCar />
    </>
  )
}

export default App
